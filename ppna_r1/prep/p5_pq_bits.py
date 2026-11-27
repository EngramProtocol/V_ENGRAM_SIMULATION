#!/usr/bin/env python3
"""Step p5 (batch dot7, ppna-r1-dot7): PQ codebooks with 4 and 6 bits per index at m = 512.

The principal configuration quantizes each embedding with m = 512 two-dimensional subquantizers
and q_PQ = 8 bits per index (256 centroids, one byte per index). Its codebooks are shipped as
data/{corpus}_pq_codebook_m512.npy and data/{corpus}_pq_codes_m512.npy. This step trains the same
quantizer with 4 and 6 bits per index (16 and 64 centroids per subquantizer) for CodeSearchNet and
SciFact with train_pq of ppna_r1/prep/common.py (faiss.ProductQuantizer, seed 1234), the routine
that built the m = 64 and m = 128 codebooks in prep step p4, and writes

    data/{corpus}_pq_codebook_m512q{q}.npy   (512, 2**q, 2) float32
    data/{corpus}_pq_codes_m512q{q}.npy      (N, 512) uint8, one index per byte

faiss packs indices shorter than 8 bits into ceil(m q / 8) bytes per object, least significant bit
first. The simulator looks up one index per subquantizer, so the codes are stored unpacked; the
record size in the manuscript counts the packed size. Two checks guard the unpacking: decoding the
unpacked indices gives the reconstruction error that faiss computes from the packed codes, and
every unpacked index is a nearest centroid of its subvector.

The step also retrains q = 8 with the same routine and compares it with the shipped codebook, so
the report shows whether the three codebooks come from one procedure. Nothing is written for q = 8.

    venv_prep/bin/python ppna_r1/prep/p5_pq_bits.py      (stage prep of run_dot7.sh)
"""
import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, REPO, log, pq_mse, save_json, save_npy, train_pq  # noqa: E402

M = 512
BITS = (4, 6)
CORPORA = ('code', 'scifact')
# s_cfg + s_tag + s_ver + s_nonce + s_root + s_sig of the core discovery record, in bytes; the
# record is RECORD_FIXED + ceil(m q / 8) bytes (680 bytes at m = 512, q = 8)
RECORD_FIXED = 168


def unpack(packed, m, nbits):
    """Indices from faiss codes: index j occupies bits j*nbits .. (j+1)*nbits - 1, LSB first."""
    if nbits == 8:
        return np.ascontiguousarray(packed[:, :m], dtype=np.uint8)
    bits = np.unpackbits(packed, axis=1, bitorder='little')[:, :m * nbits]
    bits = bits.reshape(len(packed), m, nbits).astype(np.uint16)
    idx = (bits << np.arange(nbits, dtype=np.uint16)).sum(axis=2)
    return idx.astype(np.uint8)


def nearest_check(E, cb, idx, rel_tol=1e-4):
    """(indices that differ from the numpy argmin, indices farther than the nearest centroid by
    more than rel_tol). faiss computes distances in another order, so exact ties may differ."""
    m, _, ds = cb.shape
    differ = beyond = 0
    rows = np.arange(len(E))
    for j in range(m):
        x = E[:, j * ds:(j + 1) * ds]
        d = ((x[:, None, :] - cb[j][None, :, :]) ** 2).sum(axis=2)
        dmin = d.min(axis=1)
        mine = d[rows, idx[:, j]]
        differ += int((idx[:, j] != d.argmin(axis=1)).sum())
        beyond += int((mine > dmin * (1 + rel_tol) + 1e-12).sum())
    return differ, beyond


def versions():
    out = {'python': sys.version.split()[0], 'numpy': np.__version__}
    try:
        import faiss
        out['faiss'] = getattr(faiss, '__version__', '?')
    except ImportError:
        out['faiss'] = 'missing'
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpora', default=','.join(CORPORA))
    ap.add_argument('--out', default=str(REPO / 'ppna_r1' / 'out_dot7' / 'pq_bits.json'))
    a = ap.parse_args()
    t_all = time.time()
    out = {'m': M, 'bits': list(BITS), 'record_fixed_bytes': RECORD_FIXED, 'seed': 1234,
           'versions': versions(), 'corpora': {}}
    problems = []
    for base in a.corpora.split(','):
        E = np.load(DATA / f'{base}_corpus_embeddings.npy').astype(np.float32)
        d_sub = E.shape[1] // M
        r = {'n_objects': int(len(E)), 'dim': int(E.shape[1]), 'd_sub': d_sub}

        def sizes(q):
            code = math.ceil(M * q / 8)
            return {'centroids': 1 << q, 'code_bytes': code, 'record_bytes': RECORD_FIXED + code,
                    'codebook_bytes': M * (1 << q) * d_sub * 4}

        cb8 = np.load(DATA / f'{base}_pq_codebook_m512.npy')
        c8 = np.load(DATA / f'{base}_pq_codes_m512.npy')
        r['q8_shipped'] = dict(sizes(8), mse=pq_mse(E, cb8, c8))
        cb, packed, mse, t = train_pq(E, M, nbits=8)
        idx = unpack(packed, M, 8)
        r['q8_retrained'] = {'mse': mse, 'seconds': t,
                             'codes_agree_pct': 100.0 * float((idx == c8).mean()),
                             'codebook_identical': bool(np.array_equal(cb, cb8))}
        log(f'[{base}] q=8: shipped MSE {r["q8_shipped"]["mse"]:.5f}, retrained {mse:.5f}, '
            f'codes agree on {r["q8_retrained"]["codes_agree_pct"]:.2f}% of positions')
        for q in BITS:
            cb, packed, mse, t = train_pq(E, M, nbits=q)
            if packed.shape != (len(E), math.ceil(M * q / 8)):
                problems.append(f'{base} q={q}: faiss codes have shape {packed.shape}')
            idx = unpack(packed, M, q)
            mse_unpacked = pq_mse(E, cb, idx)
            differ, beyond = nearest_check(E, cb, idx)
            if int(idx.max()) >= (1 << q):
                problems.append(f'{base} q={q}: index {int(idx.max())} out of range')
            if abs(mse_unpacked - mse) > 1e-9 * max(mse, 1e-12):
                problems.append(f'{base} q={q}: MSE {mse_unpacked} from unpacked indices, '
                                f'{mse} from faiss')
            if beyond:
                problems.append(f'{base} q={q}: {beyond} indices are not a nearest centroid')
            save_npy(cb, DATA / f'{base}_pq_codebook_m512q{q}.npy')
            save_npy(idx, DATA / f'{base}_pq_codes_m512q{q}.npy')
            r[f'q{q}'] = dict(sizes(q), mse=mse, mse_from_unpacked=mse_unpacked, seconds=t,
                              codebook_shape=list(cb.shape), packed_shape=list(packed.shape),
                              argmin_differ=differ, not_nearest=beyond)
            log(f'[{base}] q={q}: MSE {mse:.5f} (unpacked {mse_unpacked:.5f}), record '
                f'{RECORD_FIXED + math.ceil(M * q / 8)} bytes, {differ} ties, {beyond} not nearest, '
                f'{t:.0f} s')
        out['corpora'][base] = r
    out['problems'] = problems
    out['seconds'] = time.time() - t_all
    out['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    save_json(out, a.out, indent=2)
    log(f'wrote {a.out}')
    for p in problems:
        log('PROBLEM: ' + p)
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
