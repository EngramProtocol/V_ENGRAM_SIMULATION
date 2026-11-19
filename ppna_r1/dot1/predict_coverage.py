"""Dự đoán số peer phân biệt được đánh giá cho mọi cấu hình đợt 1, ghi TRƯỚC khi chạy.

Mô hình chi phí (Mục 3.6, R1-6):
    E[pi] ~= L * K * (1 + (T - 1) * min(h_K, c) / c),   h_K = log2(N_alive / K)
Lật bit ở vị trí j <= h_K đưa target sang cây con khác có hơn K peer, nên mở một
vùng K peer mới; lật ở j > h_K giữ nguyên vùng K peer. Cột chiếu độc lập cùng
phân bố nên T - 1 vị trí margin nhỏ nhất là một tập con ngẫu nhiên đều của
{1..c}. Bỏ qua chồng lấn giữa các bảng. Với khoá cụt b bit, c thay bằng min(c, b).

Monte Carlo: ID peer 63 bit đều như FastNetwork, target đều, tập lật đều trong
{1..c}, đếm đúng số peer phân biệt (có tính chồng lấn). Không cần dữ liệu thật.

Chạy một lần trước đợt 1 và commit file ra cùng patch, để dự đoán có dấu thời
gian trước kết quả:
    python3 ppna_r1/dot1/predict_coverage.py > ppna_r1/dot1/predictions_dot1.json
"""
import json
import math
import sys

import numpy as np

RNG = np.random.default_rng(20261119)
ID_BITS = 63


def closed_form(N, L, T, K, c):
    h = math.log2(N / K)
    return L * K * (1 + (T - 1) * min(h, c) / c)


def monte_carlo(N, L, T, K, c, trials):
    ids = RNG.integers(0, 2 ** ID_BITS, size=N, dtype=np.int64)
    tot = []
    for _ in range(trials):
        seen = set()
        for _t in range(L):
            x = int(RNG.integers(0, 2 ** ID_BITS))
            targets = [x]
            if T > 1:
                for j in RNG.choice(np.arange(1, c + 1), size=T - 1, replace=False):
                    targets.append(x ^ (1 << (ID_BITS - int(j))))
            for t in targets:
                d = np.bitwise_xor(ids, np.int64(t))
                seen.update(np.argpartition(d, K - 1)[:K].tolist())
        tot.append(len(seen))
    return float(np.mean(tot)), float(np.std(tot) / math.sqrt(trials))


def configs():
    """(nhóm, nhãn, N_tổng, tỉ lệ mất, L, T, K, c) cho mọi điểm đợt 1."""
    out = []
    base = dict(L=5, T=8, K=20, c=16)

    def add(group, label, N=10000, loss=0.0, **kw):
        p = dict(base)
        p.update(kw)
        out.append((group, label, N, loss, p['L'], p['T'], p['K'], p['c']))

    for T in (1, 3, 5, 8, 12):
        add('t5', f'T={T} K=20', T=T)
    for K in (10, 40, 80):
        add('t5', f'T=8 K={K}', K=K)
    for L in (3, 4, 6, 8, 10):
        add('r11', f'L={L} T=8', L=L)
    add('r11', 'L=8 T=5', L=8, T=5)
    for c in (8, 9, 12, 24):
        add('r11', f'c={c} T=8', c=c)
    add('r11', 'c=9 T=5', c=9, T=5)
    add('r11', 'c=12 T=6', c=12, T=6)
    for N in (15000, 20000, 25000, 35000, 50000):
        add('ws', f'N={N} K=20', N=N)
        add('ws', f'N={N} K={N // 500}', N=N, K=N // 500)
    for N in (10000, 25000, 50000):
        for b in (8, 10, 12, 16):
            add('trunc', f'N={N} b={b}', N=N, c=min(16, b))
    for f in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50):
        add('loss', f'loss={f:.2f}', loss=f)
    return out


def main():
    rows = []
    for group, label, N, loss, L, T, K, c in configs():
        Na = int(round(N * (1 - loss)))
        cf = closed_form(Na, L, T, K, c)
        trials = 200 if Na <= 20000 else 80
        mc, mc_se = monte_carlo(Na, L, T, K, c, trials)
        rows.append({'group': group, 'label': label, 'N': N, 'N_alive': Na, 'loss': loss,
                     'L': L, 'T': T, 'K': K, 'c': c,
                     'h_K': math.log2(Na / K),
                     'closed_form_peers': cf, 'monte_carlo_peers': mc,
                     'monte_carlo_se': mc_se, 'nominal_LTK': L * T * K,
                     'closed_form_pct': 100 * cf / N, 'monte_carlo_pct': 100 * mc / N})
        print(f'{group:5s} {label:16s} closed {cf:8.1f} MC {mc:8.1f} ({100 * mc / N:5.2f}% of N)',
              file=sys.stderr)
    # Ngoại suy recall cho weak scaling K = 20 từ ba điểm của bản đã nộp
    # (80,0 ở 10k; 71,8 ở 25k; 65,2 ở 50k): giảm khoảng 6,3 điểm mỗi lần N gấp đôi.
    slope = np.polyfit(np.log2([10000, 25000, 50000]), [80.0, 71.8, 65.2], 1)
    interp = {str(N): float(np.polyval(slope, math.log2(N))) for N in (15000, 20000, 35000)}
    json.dump({'note': 'Ghi trước khi chạy đợt 1. peers = số peer phân biệt được đánh giá '
                       'mỗi truy vấn; pct tính trên N tổng (kể cả peer đã mất).',
               'model': 'E[pi] = L*K*(1 + (T-1)*min(h_K,c)/c), h_K = log2(N_alive/K)',
               'rows': rows,
               'weak_scaling_K20_recall_interpolation': {
                   'points_from_submitted': {'10000': 80.0, '25000': 71.8, '50000': 65.2},
                   'slope_per_doubling': float(slope[0]),
                   'predicted_final_r5': interp}},
              sys.stdout, indent=1)
    print(file=sys.stdout)


if __name__ == '__main__':
    main()
