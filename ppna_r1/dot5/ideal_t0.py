"""R@5 của mô hình lý tưởng churn (main_churn_engine.py) lúc t = 0: ngay sau ingest, chưa có churn.

main_churn_engine.py đo lần đầu sau warm-up, nên không có mốc "không churn" để so. Script này dựng đúng mạng
và đúng ingest của main_churn_engine.main (cùng seed, cùng phép chiếu 63 bit, cùng ID peer) rồi gọi đúng
hàm measure_recall một lần, trước mọi bước churn. Mốc này cho phép tách suy giảm do churn (R@5 các lần đo
trừ R@5 lúc t = 0, trong cùng một mô hình) khỏi khác biệt tĩnh giữa mô hình lý tưởng churn và mô hình
iterative (khoá 63 bit so với 160 bit, rerank toàn bộ ứng viên so với kappa = 30 mỗi peer).

Chạy từ gốc repo (mỗi lần vài giây):
    python3 ppna_r1/dot5/ideal_t0.py --meta-anchors 1 4 --out-dir ppna_r1/out_dot5/ideal_t0
"""
import argparse
import json
import os
import random
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.getcwd())
import main_churn_engine as E   # noqa: E402

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def t0(ds, nodes, seed, r, nq, data, L=5, k_query=20, multi_probe=8, probe_bits=16, ses=120.0):
    emb, Qv, codes, codebook, gt = data
    n_query = min(nq, len(gt))
    # như main_churn_engine.main: ma trận chiếu từ RandomState(seed), mạng ChurnNetwork(N, seed, ...)
    rnd = np.random.RandomState(seed)
    P = [rnd.choice([-1.0, 0.0, 1.0], size=(1024, 63), p=[1/6, 2/3, 1/6]) for _ in range(L)]
    net = E.ChurnNetwork(nodes, seed, ses, 'weibull', 0.5)
    for i in range(len(emb)):
        for skey in [net.key63(emb[i], proj) for proj in P]:
            for ni in net.knn(skey, r):
                net.ram[int(ni)][i] = E.TTL_INF
    args = SimpleNamespace(multi_probe=multi_probe, probe_bits=probe_bits, k_query=k_query)
    rr, fr, tc, rand = E.measure_recall(net, P, Qv, gt, codes, codebook, args, n_query,
                                        random.Random(seed + 777))
    return {'dataset': ds, 'nodes': nodes, 'seed': seed, 'meta_anchors': r, 'nq': n_query,
            'reach_r5': rr, 'final_r5': fr, 'nodes_touched': tc, 'random_r5': rand,
            'footprint': float(np.mean([len(x) for x in net.ram])) * nodes / len(emb),
            'commit': os.environ.get('RUN_COMMIT', '')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='code')
    ap.add_argument('--nodes', type=int, default=10000)
    ap.add_argument('--nq', type=int, default=200)
    ap.add_argument('--pq', default='m512')
    ap.add_argument('--meta-anchors', type=int, nargs='+', default=[1, 4])
    ap.add_argument('--seeds', type=int, nargs='+', default=SEEDS)
    ap.add_argument('--out-dir', default='ppna_r1/out_dot5/ideal_t0')
    a = ap.parse_args()
    D = f'./data/{a.dataset}'
    with open(f'{D}_ground_truth.json', encoding='utf-8') as fh:
        gt = json.load(fh)
    data = (np.load(f'{D}_corpus_embeddings.npy'), np.load(f'{D}_query_embeddings.npy'),
            np.load(f'{D}_pq_codes_{a.pq}.npy'), np.load(f'{D}_pq_codebook_{a.pq}.npy'), gt)
    os.makedirs(a.out_dir, exist_ok=True)
    for r in a.meta_anchors:
        for s in a.seeds:
            out = t0(a.dataset, a.nodes, s, r, a.nq, data)
            p = os.path.join(a.out_dir, f'r{r}_s{s}.json')
            with open(p + '.tmp', 'w', encoding='utf-8') as fh:
                json.dump(out, fh, indent=1)
            os.replace(p + '.tmp', p)
            print(f'r = {r} seed {s}: R@5 lúc t = 0 {out["final_r5"]:.1f} (ngẫu nhiên {out["random_r5"]:.1f}, '
                  f'bản sống {out["footprint"]:.2f})', flush=True)


if __name__ == '__main__':
    main()
