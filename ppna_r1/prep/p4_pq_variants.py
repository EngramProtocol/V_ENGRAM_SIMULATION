#!/usr/bin/env python3
"""Bước p4: codebook PQ cho sweep m ở R1-1.

Có sẵn m = 256 (file không hậu tố) và m = 512 (hậu tố _m512) cho code và
SciFact. Bước này thêm m = 64 và m = 128 (hậu tố _m64, _m128), q = 8 bit, cùng
quy trình faiss.ProductQuantizer, và ghi sai số tái tạo của cả bốn mức.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, SMOKE_DIR, lib_versions, log, pq_mse, save_npy, train_pq, write_summary  # noqa: E402

NEW_M = [64, 128]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="huấn luyện m = 64 trên 2.000 vector, ghi ra data/_prep_smoke/")
    args = ap.parse_args()
    t_all = time.time()
    out = {"smoke": args.smoke, "versions": lib_versions(), "corpora": {}}
    for base in ("code", "scifact"):
        E = np.load(DATA / f"{base}_corpus_embeddings.npy").astype(np.float32)
        r = {}
        if args.smoke:
            cb, codes, mse, t = train_pq(E[:2000], 64)
            SMOKE_DIR.mkdir(parents=True, exist_ok=True)
            save_npy(cb, SMOKE_DIR / f"{base}_pq_codebook_m64.npy")
            r["m64_on_2000"] = {"mse": mse, "seconds": t, "codebook_shape": list(cb.shape)}
            out["corpora"][base] = r
            continue
        r["m256_existing_mse"] = pq_mse(E, np.load(DATA / f"{base}_pq_codebook.npy"),
                                        np.load(DATA / f"{base}_pq_codes.npy"))
        r["m512_existing_mse"] = pq_mse(E, np.load(DATA / f"{base}_pq_codebook_m512.npy"),
                                        np.load(DATA / f"{base}_pq_codes_m512.npy"))
        for m in NEW_M:
            cb, codes, mse, t = train_pq(E, m)
            save_npy(cb, DATA / f"{base}_pq_codebook_m{m}.npy")
            save_npy(codes, DATA / f"{base}_pq_codes_m{m}.npy")
            r[f"m{m}_mse"] = mse
            r[f"m{m}_seconds"] = t
            log(f"[{base}] m={m}: MSE {mse:.4f} ({t:.0f} giây)")
        log(f"[{base}] MSE có sẵn: m=256 {r['m256_existing_mse']:.4f}, m=512 {r['m512_existing_mse']:.4f}")
        out["corpora"][base] = r
    out["seconds"] = time.time() - t_all
    write_summary("p4_pq_variants_smoke" if args.smoke else "p4_pq_variants", out)
    log("p4 xong")


if __name__ == "__main__":
    main()
