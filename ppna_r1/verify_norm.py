#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kiểm nguồn gốc các bảng mô hình lý tưởng và tác động của chuẩn hoá cột chiếu.

Phần 1. Thời điểm ghi của mọi file kết quả mô hình lý tưởng (result_*.json, trừ
        result_full_* của mô hình iterative), so với lúc server nhận commit
        chuẩn hoá d48ec0b (merge 3fbb0c6, 2026-08-17 13:45:32 UTC).
Phần 2. So file cũ của cấu hình chính (L=5, K=20, r=1, T=8, PQ m512, 10 seed)
        với hai lần chạy lại bằng code hiện tại: NORMALIZE_ROWS=0 và =1.
        Chuẩn hoá không đổi dấu của phép chiếu, nên khoá gốc và vị trí record
        không đổi; nó chỉ đổi THỨ TỰ margin, tức bit nào được lật khi T > 1.
Phần 3. Đối chứng T=1: không có phép lật, hai chế độ phải trùng từng số.

Chạy:  python3 ppna_r1/verify_norm.py --out ppna_r1/out_verify_norm --nq 500
"""
import argparse
import datetime as dt
import glob
import json
import math
import os
import re
import statistics as st
from collections import defaultdict

PULL_UTC = dt.datetime(2026, 8, 17, 13, 45, 32, tzinfo=dt.timezone.utc)
FIELDS = ['reachable_recall5', 'recall5', 'mean_unique_candidates',
          'mean_nodes_touched', 'metadata_gini']
# Số đang in trong bản đã nộp (Bảng 4 và Bảng 5): mean, SD, reach mean
PAPER = {'code': (80.0, 4.8, 81.6), 'scifact': (80.0, 4.9, 81.7)}
T975 = [None, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
        2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093,
        2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045,
        2.042]


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def same(a, b):
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def all_same(x, y, fields=FIELDS):
    return x is not None and y is not None and all(same(x.get(k), y.get(k)) for k in fields)


def msd(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return float('nan'), float('nan'), 0
    return st.mean(xs), (st.stdev(xs) if len(xs) > 1 else 0.0), len(xs)


def paired(xs, ys):
    d = [y - x for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(d)
    if n < 2:
        return None
    m, s = st.mean(d), st.stdev(d)
    se = s / math.sqrt(n)
    tc = T975[min(n - 1, 30)]
    t = m / se if se > 0 else float('inf') if m else 0.0
    return {'n': n, 'mean': m, 'sd': s, 'lo': m - tc * se, 'hi': m + tc * se,
            't': t, 'max_abs': max(abs(v) for v in d), 'n_zero': sum(1 for v in d if v == 0)}


def part1(root):
    print('=' * 100)
    print('PHẦN 1. THỜI ĐIỂM GHI CỦA FILE MÔ HÌNH LÝ TƯỞNG so với 2026-08-17 13:45:32 UTC')
    print('        TRƯỚC = sinh bằng code chưa chuẩn hoá cột chiếu; SAU = đã chuẩn hoá')
    print('=' * 100)
    pat = re.compile(r'^(result_(?!full_).+?)_s(\d+)_nq(\d+)\.json$')
    groups = defaultdict(lambda: {'truoc': [], 'sau': []})
    files = glob.glob(os.path.join(root, 'result_*.json')) + \
        glob.glob(os.path.join(root, '*', 'result_*.json'))
    for p in files:
        m = pat.match(os.path.basename(p))
        if not m:
            continue
        rel = os.path.relpath(os.path.dirname(p), root)
        cfg = f'{m.group(1)}_nq{m.group(3)}'
        if rel != '.':
            cfg = f'{rel}/{cfg}'
        t = dt.datetime.fromtimestamp(os.path.getmtime(p), tz=dt.timezone.utc)
        groups[cfg]['truoc' if t < PULL_UTC else 'sau'].append(int(m.group(2)))
    n_mix = n_old = n_new = 0
    print(f"{'nhóm':6s} {'trước':>5s} {'sau':>4s}  cấu hình")
    for cfg in sorted(groups):
        g = groups[cfg]
        nb, na = len(g['truoc']), len(g['sau'])
        if nb and na:
            tag, n_mix = 'TRỘN', n_mix + 1
        elif nb:
            tag, n_old = 'TRƯỚC', n_old + 1
        else:
            tag, n_new = 'SAU', n_new + 1
        extra = f"   seed sau mốc: {sorted(g['sau'])}" if tag == 'TRỘN' else ''
        print(f'{tag:6s} {nb:5d} {na:4d}  {cfg}{extra}')
    print(f'\n  {len(groups)} cấu hình: {n_old} toàn TRƯỚC, {n_new} toàn SAU, {n_mix} TRỘN')
    return groups


def part2(root, out, nq, seeds):
    print('\n' + '=' * 100)
    print('PHẦN 2. CẤU HÌNH CHÍNH: file cũ so với chạy lại NORMALIZE_ROWS=0 và =1')
    print('=' * 100)
    verdict = {}
    for ds in ('code', 'scifact'):
        base = f'result_{ds}_N10000_L5_K20_MA1_T8_m512'
        old = {s: load(os.path.join(root, f'{base}_s{s}_nq{nq}.json')) for s in seeds}
        bak = {s: load(os.path.join(root, 'backup_hotspot', f'{base}_s{s}_nq{nq}.json')) for s in seeds}
        n0 = {s: load(os.path.join(out, f'{ds}_T8_norm0_s{s}.json')) for s in seeds}
        n1 = {s: load(os.path.join(out, f'{ds}_T8_norm1_s{s}.json')) for s in seeds}

        print(f'\n--- {ds} ---')
        print(f"{'seed':>9s} {'R@5 cũ':>9s} {'norm=0':>9s} {'norm=1':>9s} {'reach cũ':>9s} "
              f"{'reach n1':>9s} {'peer% n1-n0':>12s}  cũ=norm0  cũ=norm1  backup=cũ")
        for s in seeds:
            o, a, b, k = old[s], n0[s], n1[s], bak[s]
            g = lambda d, f: (f'{d[f]:9.2f}' if d and f in d else f"{'-':>9s}")
            dpeer = (f"{(b['pct_network_touched'] - a['pct_network_touched']):12.3f}"
                     if a and b and 'pct_network_touched' in a and 'pct_network_touched' in b
                     else f"{'-':>12s}")
            print(f'{s:>9d} {g(o, "recall5")} {g(a, "recall5")} {g(b, "recall5")} '
                  f'{g(o, "reachable_recall5")} {g(b, "reachable_recall5")} {dpeer}  '
                  f'{"có" if all_same(o, a) else "KHÔNG":>8s}  {"có" if all_same(o, b) else "KHÔNG":>8s}  '
                  f'{("có" if all_same(k, o) else "KHÔNG") if k else "-":>9s}')

        have = [s for s in seeds if old[s] and n0[s]]
        match0 = [s for s in have if all_same(old[s], n0[s])]
        match1 = [s for s in seeds if old[s] and n1[s] and all_same(old[s], n1[s])]
        print('\n  Trùng theo từng trường (số seed khớp / số seed có đủ file):')
        for f in FIELDS:
            c0 = sum(1 for s in have if same(old[s].get(f), n0[s].get(f)))
            c1 = sum(1 for s in seeds if old[s] and n1[s] and same(old[s].get(f), n1[s].get(f)))
            print(f'    {f:24s}  cũ=norm0: {c0}/{len(have)}   cũ=norm1: {c1}/{len(have)}')

        for name, d in (('file cũ', old), ('norm=0', n0), ('norm=1', n1)):
            m5, s5, n5 = msd([d[s]['recall5'] for s in seeds if d[s]])
            mr, _, _ = msd([d[s]['reachable_recall5'] for s in seeds if d[s]])
            print(f'  {name:8s}: Final R@5 = {m5:.1f} ± {s5:.1f} (n={n5}), Reach = {mr:.1f}')
        pm, ps, pr = PAPER[ds]
        print(f'  bài in   : Final R@5 = {pm:.1f} ± {ps:.1f}, Reach = {pr:.1f}')

        for f, lab in (('recall5', 'Final R@5'), ('reachable_recall5', 'Reach R@5'),
                       ('pct_network_touched', 'peer %')):
            p = paired([n0[s][f] if n0[s] else None for s in seeds],
                       [n1[s][f] if n1[s] else None for s in seeds])
            if p:
                print(f'  tác động chuẩn hoá ({lab}, norm1 - norm0): {p["mean"]:+.3f} điểm, '
                      f'KTC95 [{p["lo"]:+.3f}, {p["hi"]:+.3f}], t({p["n"] - 1}) = {p["t"]:.2f}, '
                      f'lệch lớn nhất một seed {p["max_abs"]:.3f}, {p["n_zero"]}/{p["n"]} seed không đổi')

        if have and len(match0) == len(have):
            v = 'XÁC NHẬN: file cũ trùng từng số với bản KHÔNG chuẩn hoá -> sinh trước d48ec0b'
        elif match1 and len(match1) == len([s for s in seeds if old[s]]):
            v = 'BÁC BỎ: file cũ trùng bản CÓ chuẩn hoá -> đã là số mới, nghi vấn sai cho cấu hình này'
        else:
            miss = sorted(set(have) - set(match0))
            v = (f'CHƯA RÕ: file cũ không trùng hẳn bản nào (seed lệch so với norm=0: {miss}). '
                 f'Có khác biệt ngoài chuẩn hoá (PQ, ground truth hoặc dòng ngẫu nhiên); gửi lại để truy')
        verdict[ds] = v
        print(f'  => {v}')
    return verdict


def part3(out, ctrl_seeds):
    print('\n' + '=' * 100)
    print('PHẦN 3. ĐỐI CHỨNG T=1 (không lật bit): norm=0 và norm=1 phải trùng từng số')
    print('=' * 100)
    ok = True
    for s in ctrl_seeds:
        a = load(os.path.join(out, f'code_T1_norm0_s{s}.json'))
        b = load(os.path.join(out, f'code_T1_norm1_s{s}.json'))
        r = all_same(a, b)
        ok &= r
        print(f'  seed {s:>9d}: {"KHỚP" if r else "LỆCH"}' +
              (f'  (R@5 {a["recall5"]:.3f} / {b["recall5"]:.3f})' if a and b else '  (thiếu file)'))
    print(f'  => {"KHỚP: phép so A/B sạch" if ok else "LỆCH: có nguồn khác biệt ngoài thứ tự margin"}')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--out', default='ppna_r1/out_verify_norm')
    ap.add_argument('--nq', type=int, default=500)
    ap.add_argument('--seeds', type=int, nargs='+',
                    default=[20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    ap.add_argument('--ctrl-seeds', type=int, nargs='+', default=[20235956, 1, 2])
    a = ap.parse_args()
    part1(a.root)
    v = part2(a.root, a.out, a.nq, a.seeds)
    c = part3(a.out, a.ctrl_seeds)
    print('\n' + '=' * 100)
    print('KẾT LUẬN')
    print('=' * 100)
    for ds, txt in v.items():
        print(f'  {ds}: {txt}')
    print(f'  đối chứng T=1: {"đạt" if c else "KHÔNG đạt"}')


if __name__ == '__main__':
    main()
