"""R1-1: tỉ lệ hai vector cho cùng bit sketch, theo góc giữa chúng.

Với phép chiếu đẳng hướng (Gaussian), xác suất một bit trùng là 1 - theta/pi
(Eq. 4). Phép chiếu Achlioptas thưa của bài chỉ xấp xỉ tính chất này. Script đo
tỉ lệ trùng thực tế cho cả hai họ, cùng chuẩn hoá cột, trên các cặp (query, object)
của corpus thật: 10 láng giềng gần nhất của mỗi query (góc nhỏ) và R object ngẫu
nhiên (góc lớn). Mỗi cặp tính trên 160 cột x L bảng, mỗi seed một bộ ma trận như
mô phỏng.

    python3 ppna_r1/dot1/bit_collision.py --dataset code --seeds 20235956,1,2 --out f.json
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.getcwd())
import src.routing as routing  # noqa: E402

BIN_DEG = 5.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='code')
    ap.add_argument('--seeds', default='20235956,1,2,3,4,5,6,7,8,9')
    ap.add_argument('--tables', type=int, default=5)
    ap.add_argument('--random-per-query', type=int, default=20)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(',') if x]

    D = f'data/{a.dataset}'
    E = np.load(f'{D}_corpus_embeddings.npy').astype(np.float32)
    Q = np.load(f'{D}_query_embeddings.npy').astype(np.float32)
    gt = json.load(open(f'{D}_ground_truth.json', encoding='utf-8'))
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    rs = np.random.RandomState(12345)
    qi, di = [], []
    for q, item in enumerate(gt[:len(Q)]):
        nn = [r['index'] for r in item['top_10_results']]
        rnd = rs.choice(len(E), size=a.random_per_query, replace=False).tolist()
        for d in nn + rnd:
            qi.append(q)
            di.append(int(d))
    qi, di = np.array(qi), np.array(di)
    cos = np.einsum('ij,ij->i', Q[qi], E[di])
    theta = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
    docs = np.unique(di)
    pos = {int(d): k for k, d in enumerate(docs)}
    dk = np.array([pos[int(d)] for d in di])
    Ed = E[docs]
    nb = int(np.ceil(180 / BIN_DEG))
    b_of = np.minimum((theta // BIN_DEG).astype(int), nb - 1)
    print(f'[*] {a.dataset}: {len(qi):,} cặp, góc {theta.min():.1f}..{theta.max():.1f} độ, '
          f'{len(seeds)} seed x {a.tables} bảng x 160 cột', flush=True)

    out = {'dataset': a.dataset, 'seeds': seeds, 'tables': a.tables, 'columns': 160,
           'normalize_cols': bool(routing.NORMALIZE_ROWS), 'n_pairs': int(len(qi)),
           'random_per_query': a.random_per_query, 'bin_deg': BIN_DEG,
           'commit': os.environ.get('RUN_COMMIT', ''), 'families': {}}
    cnt = np.bincount(b_of, minlength=nb)
    th_mean = np.bincount(b_of, weights=theta, minlength=nb) / np.maximum(cnt, 1)
    theory_pair = 1.0 - theta / 180.0
    for fam in ('achlioptas', 'gaussian'):
        routing.ZERO_COLUMNS_REDRAWN = 0
        per_seed_bins, per_seed_pair_mae, per_seed_mean_dev = [], [], []
        for s in seeds:
            P = routing.generate_lsh_projections(s, vector_dim=E.shape[1],
                                                 num_projections=a.tables, family=fam)
            agree = np.zeros(len(qi))
            for M in P:
                bq = (Q @ M) > 0
                bd = (Ed @ M) > 0
                agree += (bq[qi] == bd[dk]).mean(axis=1)
            agree /= len(P)
            per_seed_bins.append((np.bincount(b_of, weights=agree, minlength=nb)
                                  / np.maximum(cnt, 1)).tolist())
            per_seed_pair_mae.append(float(np.mean(np.abs(agree - theory_pair))))
            per_seed_mean_dev.append(float(np.mean(agree - theory_pair)))
        B = np.array(per_seed_bins)
        mean_b = B.mean(axis=0)
        theory_b = 1.0 - th_mean / 180.0
        good = cnt >= 100
        dev = mean_b - theory_b
        out['families'][fam] = {
            'zero_columns_redrawn': int(routing.ZERO_COLUMNS_REDRAWN),
            'bins': [{'lo': i * BIN_DEG, 'hi': (i + 1) * BIN_DEG, 'n': int(cnt[i]),
                      'theta_mean': float(th_mean[i]), 'agree_mean': float(mean_b[i]),
                      'agree_sd_seeds': float(B[:, i].std(ddof=1)) if len(seeds) > 1 else 0.0,
                      'theory': float(theory_b[i])} for i in range(nb) if cnt[i] > 0],
            'max_abs_dev_bins_n100': float(np.max(np.abs(dev[good]))) if good.any() else None,
            'weighted_mean_abs_dev': float(np.sum(np.abs(dev) * cnt) / cnt.sum()),
            'pair_mae_per_seed': per_seed_pair_mae,
            'pair_mean_dev_per_seed': per_seed_mean_dev,
        }
        print(f'    {fam:10s}: lệch tuyệt đối TB theo bin {out["families"][fam]["weighted_mean_abs_dev"]:.4f}, '
              f'lớn nhất {out["families"][fam]["max_abs_dev_bins_n100"]:.4f}', flush=True)
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=1)
    print(f'-> {a.out}')


if __name__ == '__main__':
    main()
