#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phân tích đợt kiểm Mục 2.1–2.4 của tài liệu sửa bài (tag ppna-r1-verify-s2).

Phần A  file cũ có sẵn trên server (không chạy gì)
  A1  các hàng 5 seed của Bảng 4 và Bảng 5: seed nào có, ghi lúc nào, trung bình
  A2  Bảng 8, 9 (repl_*, fail_*): số seed, thời điểm ghi, phiên bản phép chiếu
  A3  Bảng 7 (q5_termabl_*): tỉ lệ lookup chạm R_max, số vòng mỗi lookup
  A4  log availability của Bảng 9 (failure_code_r*_s*.txt): overlay nào, số nào
  A5  Bảng 6 (lsh10_*): ghi trước hay sau mốc chuẩn hoá
Phần B  2.1: đủ 10 seed cho các hàng 5 seed, so hồi quy với file cũ
Phần C  2.2, 2.3: tách quy tắc dừng theo pha trong mô hình iterative
Phần D  2.4: availability trên k-bucket có seed, đối chiếu ring

Chạy trên server, ở gốc repo:
    python3 ppna_r1/verify_s2.py --parts ABCD
Chạy lại từ file tar (file cũ nằm trong ppna_r1/snap_existing):
    python3 ppna_r1/verify_s2.py --parts ABCD --root ppna_r1/snap_existing
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
KBUCKET_UTC = dt.datetime(2026, 8, 14, 9, 10, 49, tzinfo=dt.timezone.utc)  # commit 64d6456
SEEDS10 = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
SEEDS5 = [20235956, 1, 2, 3, 4]
CORPUS = {'code': 20000, 'scifact': 5183}
T975 = [None, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
        2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086]
FIELDS_V2 = ['recall5', 'reachable_recall5', 'mean_unique_candidates',
             'mean_nodes_touched', 'metadata_gini']
FIELDS_ITER = ['recall_at_5', 'reachable_recall5', 'rpc_routing_mean', 'rpc_eval_mean',
               'mean_rpcs', 'xor_rank_mean', 'metadata_gini', 'mean_contacted',
               'mean_candidates', 'lookups_at_cap']
VARS = ['stable-all', 'stable-topk', 'exhaust-all', 'exhaust-topk']

# ---- số in trong bản đã nộp ----
# Bảng 5 (CodeSearchNet): Reach, Final, Peers %, Cand. %
PAPER_T5 = {'code_T1_K20': (39.9, 39.8, 1.0, 5.7), 'code_T12_K20': (87.6, 85.4, 7.0, 29.7),
            'code_T8_K10': (74.0, 73.0, 2.7, 14.5), 'code_T8_K40': (88.6, 86.3, 8.9, 33.4),
            'code_T8_K80': (94.7, 91.7, 15.7, 48.3)}
# Bảng 4, hàng candidate threshold: Final mean, SD, Peers %, Cand. %
PAPER_T4C = {'code_randcand': (47.4, 9.6, 12.6, 32.7), 'scifact_randcand': (55.5, 7.8, 16.1, 45.9)}
OLD_NAME = {'code_T1_K20': 'result_code_N10000_L5_K20_MA1_T1_m512',
            'code_T12_K20': 'result_code_N10000_L5_K20_MA1_T12_m512',
            'code_T8_K10': 'result_code_N10000_L5_K10_MA1_T8_m512',
            'code_T8_K40': 'result_code_N10000_L5_K40_MA1_T8_m512',
            'code_T8_K80': 'result_code_N10000_L5_K80_MA1_T8_m512',
            'code_randcand': 'result_code_N10000_L5_K20_MA1_T8_m512_RANDCAND',
            'scifact_randcand': 'result_scifact_N10000_L5_K20_MA1_T8_m512_RANDCAND'}
# Bảng 7: Reach, Final, SD, Rout., Eval., Total, XOR rank
PAPER_T7 = {'stable-all': (76.2, 75.1, 5.4, 828, 490, 1319, 53.6),
            'stable-topk': (70.3, 69.6, 5.5, 827, 490, 1317, 53.8),
            'exhaust-all': (80.6, 79.2, 4.9, 1800, 492, 2292, 15.4),
            'exhaust-topk': (67.3, 66.6, 5.6, 1362, 490, 1852, 20.2)}
PAPER_T8 = {1: (80.0, 4.8), 2: (80.3, 4.7), 4: (80.6, 4.6), 5: (80.8, 4.5), 10: (81.6, 4.4)}
PAPER_T8_RAND = {1: 34.5, 2: 56.4, 4: 79.8, 5: 85.4, 10: 94.9}
# Bảng 9: Final mean, SD, Routable metadata %, Routable payload %
PAPER_T9 = {(1, 0): (80.0, 4.8, 99.9, 100.0), (1, 20): (74.6, 5.0, 99.4, 96.7),
            (1, 30): (71.5, 5.0, 98.0, 74.5), (2, 30): (80.9, 4.6, 99.8, 74.6),
            (3, 30): (82.8, 4.1, 99.9, 72.1)}


# ======================================================================= tiện ích
def load(p):
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def mtime(p):
    return dt.datetime.fromtimestamp(os.path.getmtime(p), tz=dt.timezone.utc)


def find(root, pattern):
    """root/pattern và root/*/pattern, bỏ thư mục ppna_r1 (trừ khi root nằm trong đó)."""
    out = []
    for p in glob.glob(os.path.join(root, pattern)) + glob.glob(os.path.join(root, '*', pattern)):
        rel = os.path.relpath(p, root)
        if rel.startswith('ppna_r1' + os.sep):
            continue
        out.append(p)
    return sorted(out)


def seed_of(p):
    m = re.search(r'_s(\d+)(?:_nq\d+)?\.(?:json|txt)$', os.path.basename(p))
    return int(m.group(1)) if m else None


def msd(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None, 0
    return st.mean(xs), (st.stdev(xs) if len(xs) > 1 else 0.0), len(xs)


def f1(x, w=6, d=1):
    return f'{x:{w}.{d}f}' if isinstance(x, (int, float)) and x == x else f"{'-':>{w}s}"


def paired(xs, ys):
    """Hiệu ys - xs ghép theo vị trí; trả (mean, lo, hi, n) hoặc None."""
    d = [y - x for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(d)
    if n < 2:
        return (d[0], None, None, 1) if n == 1 else None
    m, s = st.mean(d), st.stdev(d)
    tc = T975[min(n - 1, len(T975) - 1)]
    return m, m - tc * s / math.sqrt(n), m + tc * s / math.sqrt(n), n


def fmt_pair(p):
    if p is None:
        return '-'
    m, lo, hi, n = p
    if lo is None:
        return f'{m:+.2f} (n=1)'
    return f'{m:+.2f} [{lo:+.2f}; {hi:+.2f}] n={n}'


def same(a, b):
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def when(paths):
    if not paths:
        return '-'
    ts = sorted(mtime(p) for p in paths)
    nb = sum(1 for t in ts if t < PULL_UTC)
    return f'{nb} trước / {len(ts) - nb} sau mốc ({ts[0]:%d/%m %H:%M} → {ts[-1]:%d/%m %H:%M} UTC)'


def header(t):
    print('\n' + '=' * 100)
    print(t)
    print('=' * 100)


def v2_stats(d, ds):
    return (d.get('reachable_recall5'), d.get('recall5'), d.get('pct_network_touched'),
            100.0 * d['mean_unique_candidates'] / CORPUS[ds] if d.get('mean_unique_candidates') is not None else None)


# ======================================================================= phần A
def part_a(root, vn_dir):
    header('A1. CÁC HÀNG 5 SEED CỦA BẢNG 4 VÀ BẢNG 5: file cũ trên server')
    print(f"{'cấu hình':18s} {'seed có':28s} {'R@5':>6s} {'SD':>5s} {'Reach':>6s} {'Peers':>6s} {'Cand':>6s}   bài in (R@5 / Reach / Peers / Cand)")
    for key, base in OLD_NAME.items():
        ds = key.split('_')[0]
        files = [p for p in find(root, f'{base}_s*_nq500.json') if seed_of(p) is not None]
        seeds = sorted(seed_of(p) for p in files)
        rows = [v2_stats(load(p) or {}, ds) for p in files]
        r5 = msd([r[1] for r in rows])
        reach = msd([r[0] for r in rows])[0]
        peers = msd([r[2] for r in rows])[0]
        cand = msd([r[3] for r in rows])[0]
        if key in PAPER_T5:
            pr = PAPER_T5[key]
            ptxt = f'{pr[1]:.1f} / {pr[0]:.1f} / {pr[2]:.1f} / {pr[3]:.1f}'
        else:
            pr = PAPER_T4C[key]
            ptxt = f'{pr[0]:.1f} ± {pr[1]:.1f} / - / {pr[2]:.1f} / {pr[3]:.1f}'
        print(f"{key:18s} {str(seeds):28s} {f1(r5[0])} {f1(r5[1], 5)} {f1(reach)} {f1(peers)} {f1(cand)}   {ptxt}")
        print(f"{'':18s} thời điểm ghi: {when(files)}")
    print('\n  Nếu R@5 năm seed ở trên trùng số in trong bài, thì bài đang in trung bình năm seed'
          ' trong khi chú thích ghi mười.')

    header('A2. BẢNG 8 VÀ BẢNG 9 (cột Final R@5): file repl_* và fail_*')
    print(f"{'nhóm':12s} {'n':>3s} {'R@5':>6s} {'SD':>5s}   {'bài in':>12s}   thời điểm ghi")
    for r in (1, 2, 3, 4, 5, 10):
        files = find(root, f'repl_r{r}_s*.json')
        v = msd([(load(p) or {}).get('recall5') for p in files])
        pp = PAPER_T8.get(r)
        ptxt = f'{pp[0]:.1f} ± {pp[1]:.1f}' if pp else '-'
        print(f"{'repl r=' + str(r):12s} {v[2]:3d} {f1(v[0])} {f1(v[1], 5)}   {ptxt:>12s}   {when(files)}")
    for lab, pat, key in (('loss 0%', 'fail_L0_s*.json', (1, 0)), ('loss 10%', 'fail_L10_s*.json', None),
                          ('loss 20%', 'fail_L20_s*.json', (1, 20)), ('loss 30%', 'fail_L30_s*.json', (1, 30)),
                          ('r2 loss 30%', 'fail_r2L30_s*.json', (2, 30)), ('r3 loss 30%', 'fail_r3L30_s*.json', (3, 30))):
        files = find(root, pat)
        v = msd([(load(p) or {}).get('recall5') for p in files])
        pp = PAPER_T9.get(key) if key else None
        ptxt = f'{pp[0]:.1f} ± {pp[1]:.1f}' if pp else '-'
        print(f"{lab:12s} {v[2]:3d} {f1(v[0])} {f1(v[1], 5)}   {ptxt:>12s}   {when(files)}")
    # phiên bản phép chiếu: so repl_r1 với hai bản chạy lại ở đợt kiểm chuẩn hoá
    keys = ('recall5', 'mean_unique_candidates', 'mean_nodes_touched')
    n = c0 = c1 = 0
    for s in SEEDS10:
        cand = find(root, f'repl_r1_s{s}.json')
        if not cand:
            continue
        x = load(cand[0]) or {}
        a = load(os.path.join(vn_dir, f'code_T8_norm0_s{s}.json')) or {}
        b = load(os.path.join(vn_dir, f'code_T8_norm1_s{s}.json')) or {}
        n += 1
        c0 += all(same(x.get(k), a.get(k)) for k in keys)
        c1 += all(same(x.get(k), b.get(k)) for k in keys)
    print(f"\n  repl_r1 so với đợt kiểm chuẩn hoá: {n} file, trùng bản CHƯA chuẩn hoá {c0}, "
          f"trùng bản ĐÃ chuẩn hoá {c1}")
    print('  Hàng "Random, nominal" của Bảng 8 (file result_..._MA{r}_T8_m512_RANDOM):')
    for r in (1, 2, 4, 5, 10):
        files = find(root, f'result_code_N10000_L5_K20_MA{r}_T8_m512_RANDOM_s*_nq500.json')
        v = msd([(load(p) or {}).get('recall5') for p in files])
        print(f"    r={r:<3d} n={v[2]:2d}  R@5 {f1(v[0])}   bài in {PAPER_T8_RAND[r]:.1f}")

    header('A3. BẢNG 7 (q5_termabl_*): lookup truy vấn có chạy hết R_max không (mục 2.2)')
    print(f"{'biến thể':13s} {'n':>3s} {'Final':>6s} {'Reach':>6s} {'Rout.':>7s} {'Eval.':>6s} {'Total':>7s} "
          f"{'XOR':>6s} {'%chạm R_max':>11s} {'vòng/lookup':>11s}   bài in (Final / Rout. / XOR)")
    for var in VARS:
        files = find(root, f'q5_termabl_{var}_s*.json')
        ds_ = [load(p) or {} for p in files]
        fin = msd([d.get('recall_at_5') for d in ds_])
        reach = msd([d.get('reachable_recall5') for d in ds_])[0]
        rout = msd([d.get('rpc_routing_mean') for d in ds_])[0]
        ev = msd([d.get('rpc_eval_mean') for d in ds_])[0]
        tot = msd([d.get('mean_rpcs') for d in ds_])[0]
        xr = msd([d.get('xor_rank_mean') for d in ds_])[0]
        lt = sum(d.get('lookups_total') or 0 for d in ds_)
        lc = sum(d.get('lookups_at_cap') or 0 for d in ds_)
        rounds = msd([(d.get('disc_rounds') / 40.0) if d.get('disc_rounds') is not None else None for d in ds_])[0]
        p = PAPER_T7[var]
        cap = f'{100.0 * lc / lt:10.1f}%' if lt else f"{'-':>11s}"
        print(f"{var:13s} {fin[2]:3d} {f1(fin[0])} {f1(reach)} {f1(rout, 7, 0)} {f1(ev, 6, 0)} {f1(tot, 7, 0)} "
              f"{f1(xr)} {cap} {f1(rounds, 11, 2)}   {p[1]:.1f} / {p[3]} / {p[6]:.1f}")
    print('  Với R_max = 15, alpha = 3 và 40 target: chạy hết ngân sách cho đúng 40 x 15 x 3 = 1.800 routing RPC.')

    header('A4. LOG AVAILABILITY CỦA BẢNG 9 (failure_code_r*_s*.txt)')
    agg = defaultdict(list)
    files = find(root, 'failure_code_r*_s*.txt')
    if not files:
        print('  không thấy file nào')
    for p in files:
        txt = open(p, encoding='utf-8', errors='ignore').read()
        topo = ('ring' if 'Small-World' in txt else 'kbucket' if 'k-bucket' in txt else 'không rõ')
        m = re.search(r'_r(\d+)_s(\d+)', os.path.basename(p))
        r = int(m.group(1)) if m else None
        rows = re.findall(r'^\s*(\d+)%\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%', txt, re.M)
        t = mtime(p)
        print(f"  {os.path.relpath(p, root):38s} ghi {t:%d/%m/%Y %H:%M} UTC | overlay: {topo:8s} | "
              f"{'trước' if t < KBUCKET_UTC else 'SAU'} ngày có code k-bucket (14/8)")
        for loss, me, pa, e2 in rows:
            agg[(r, int(loss))].append((float(me), float(pa)))
            print(f"      mất {loss:>2s}%: metadata {me:>5s}%  payload {pa:>5s}%")
    if agg:
        print('\n  Trung bình mọi file (cách analyze_failure.py tổng hợp) so với Bảng 9:')
        for key, (pf, psd, pm, pp) in PAPER_T9.items():
            v = agg.get(key, [])
            if v:
                print(f"    r={key[0]} mất {key[1]:>2d}%: n={len(v)} metadata {st.mean(x[0] for x in v):5.1f}% "
                      f"(bài {pm:.1f})  payload {st.mean(x[1] for x in v):5.1f}% (bài {pp:.1f})")

    header('A5. BẢNG 6 (Bucket-LSH, lsh10_*): ghi trước hay sau mốc chuẩn hoá')
    lst = os.path.join(root, 'lsh10_listing.txt')
    if os.path.exists(lst):
        ts = re.findall(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+\S*lsh10_', open(lst).read())
        ts = [dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc) for t in ts]
    else:
        ts = [mtime(p) for p in find(root, 'lsh10_*.txt')]
    if ts:
        nb = sum(1 for t in ts if t < PULL_UTC)
        print(f"  {len(ts)} file: {nb} trước mốc, {len(ts) - nb} sau mốc "
              f"({min(ts):%d/%m %H:%M} → {max(ts):%d/%m %H:%M} UTC)")
    else:
        print('  không thấy file lsh10_*')


# ======================================================================= phần B
def part_b(root, out):
    header('B. MỤC 2.1: CÁC HÀNG 5 SEED CHẠY ĐỦ 10 SEED (code chưa chuẩn hoá, như bản đã nộp)')
    print(f"{'cấu hình':18s} {'hồi quy 5 seed cũ':18s} {'R@5 5 seed':>10s} {'R@5 10 seed':>11s} {'SD':>5s} "
          f"{'dịch':>6s} {'Reach10':>7s} {'Peers10':>7s} {'Cand10':>6s}   bài in")
    for key, base in OLD_NAME.items():
        ds = key.split('_')[0]
        new = {s: load(os.path.join(out, 'B', f'{key}_s{s}.json')) for s in SEEDS10}
        old = {}
        for s in SEEDS5:
            c = find(root, f'{base}_s{s}_nq500.json')
            old[s] = load(c[0]) if c else None
        have = [s for s in SEEDS5 if old[s] and new[s]]
        match = sum(1 for s in have if all(same(old[s].get(f), new[s].get(f)) for f in FIELDS_V2))
        reg = f'{match}/{len(have)} trùng' if have else 'thiếu file'
        r5_10 = msd([new[s]['recall5'] for s in SEEDS10 if new[s]])
        r5_5 = msd([new[s]['recall5'] for s in SEEDS5 if new[s]])[0]
        st10 = [v2_stats(new[s], ds) for s in SEEDS10 if new[s]]
        reach = msd([x[0] for x in st10])[0]
        peers = msd([x[2] for x in st10])[0]
        cand = msd([x[3] for x in st10])[0]
        shift = (r5_10[0] - r5_5) if (r5_10[0] is not None and r5_5 is not None) else None
        if key in PAPER_T5:
            pr = PAPER_T5[key]
            ptxt = f'{pr[1]:.1f} (reach {pr[0]:.1f}, peers {pr[2]:.1f}, cand {pr[3]:.1f})'
        else:
            pr = PAPER_T4C[key]
            ptxt = f'{pr[0]:.1f} ± {pr[1]:.1f} (peers {pr[2]:.1f}, cand {pr[3]:.1f})'
        print(f"{key:18s} {reg:18s} {f1(r5_5, 10)} {f1(r5_10[0], 11)} {f1(r5_10[1], 5)} "
              f"{f1(shift, 6, 2)} {f1(reach, 7)} {f1(peers, 7)} {f1(cand, 6)}   {ptxt}   (n={r5_10[2]})")
    print('\n  "dịch" = trung bình 10 seed trừ trung bình 5 seed đầu. "hồi quy" phải là 5/5 trùng.')


# ======================================================================= phần C
def part_c(root, out):
    header('C. MỤC 2.2 VÀ 2.3: QUY TẮC DỪNG THEO PHA, MÔ HÌNH ITERATIVE (k-bucket, join)')
    cdir = os.path.join(out, 'C')
    seeds = sorted({int(m.group(1)) for p in glob.glob(os.path.join(cdir, '*_s*.json'))
                    if (m := re.search(r'_s(\d+)\.json$', p))}, key=lambda s: SEEDS10.index(s) if s in SEEDS10 else 99)
    if not seeds:
        print('  chưa có kết quả nhóm C')
        return
    R = lambda kind, var, s: load(os.path.join(cdir, f'{kind}_{var}_s{s}.json'))

    def old(var, s):
        c = find(root, f'q5_termabl_{var}_s{s}.json')
        return load(c[0]) if c else None

    print(f'  seed: {seeds}')
    print('\n  C0. Hồi quy: cấu hình chính chạy bằng code vá so với file Bảng 7 cũ (q5_termabl_stable-all)')
    for s in seeds:
        a, b = old('stable-all', s), R('main', 'stable-all', s)
        if not (a and b):
            print(f'    seed {s}: thiếu file ({"cũ" if not a else "mới"})')
            continue
        bad = [f for f in FIELDS_ITER if not same(a.get(f), b.get(f))]
        print(f"    seed {s:>9d}: {len(FIELDS_ITER) - len(bad)}/{len(FIELDS_ITER)} trường trùng"
              f"{'' if not bad else '  LỆCH: ' + ', '.join(bad)}")
    print('  Pha dựng mạng của biến thể cũ (metadata_gini của b_<X> so với q5_termabl_<X>), và của'
          ' các lần chỉ đổi truy vấn so với main:')
    for var in VARS[1:]:
        m1 = [same((old(var, s) or {}).get('metadata_gini'), (R('b', var, s) or {}).get('metadata_gini'))
              for s in seeds if old(var, s) and R('b', var, s)]
        m2 = [same((R('main', 'stable-all', s) or {}).get('metadata_gini'), (R('q', var, s) or {}).get('metadata_gini'))
              for s in seeds if R('main', 'stable-all', s) and R('q', var, s)]
        print(f"    {var:13s} b_ trùng file cũ {sum(m1)}/{len(m1)} | q_ trùng main {sum(m2)}/{len(m2)}")

    print('\n  C1. Final R@5 (%) và chi phí truy vấn, trên cùng các seed')
    print(f"  {'biến thể':13s} {'bài (mọi pha X)':>16s} {'chỉ truy vấn X':>15s} {'phần do dựng+ingest':>26s} "
          f"{'Rout. bài':>9s} {'Rout. mới':>9s} {'XOR bài':>8s} {'XOR mới':>8s}")
    base_old = [((old('stable-all', s) or {}).get('recall_at_5')) for s in seeds]
    base_new = [((R('main', 'stable-all', s) or {}).get('recall_at_5')) for s in seeds]
    for var in VARS:
        po = [(old(var, s) or {}).get('recall_at_5') for s in seeds]
        qn = [((R('main', 'stable-all', s) if var == 'stable-all' else R('q', var, s)) or {}).get('recall_at_5')
              for s in seeds]
        ro = msd([(old(var, s) or {}).get('rpc_routing_mean') for s in seeds])[0]
        rn = msd([((R('main', 'stable-all', s) if var == 'stable-all' else R('q', var, s)) or {}).get('rpc_routing_mean') for s in seeds])[0]
        xo = msd([(old(var, s) or {}).get('xor_rank_mean') for s in seeds])[0]
        xn = msd([((R('main', 'stable-all', s) if var == 'stable-all' else R('q', var, s)) or {}).get('xor_rank_mean') for s in seeds])[0]
        a, b = msd(po), msd(qn)
        print(f"  {var:13s} {f1(a[0], 9)} ± {f1(a[1], 4)} {f1(b[0], 8)} ± {f1(b[1], 4)} {fmt_pair(paired(qn, po)):>26s} "
              f"{f1(ro, 9, 0)} {f1(rn, 9, 0)} {f1(xo, 8)} {f1(xn, 8)}")
    print('\n  Chênh so với cấu hình chính (điểm, KTC 95% ghép cặp theo seed):')
    print(f"  {'biến thể':13s} {'như bài (mọi pha đổi)':>30s} {'chỉ đổi truy vấn':>30s}   bài in")
    for var in VARS[1:]:
        po = [(old(var, s) or {}).get('recall_at_5') for s in seeds]
        qn = [(R('q', var, s) or {}).get('recall_at_5') for s in seeds]
        p = PAPER_T7[var][1] - PAPER_T7['stable-all'][1]
        print(f"  {var:13s} {fmt_pair(paired(base_old, po)):>30s} {fmt_pair(paired(base_new, qn)):>30s}   {p:+.1f}")
    for kind, lab in (('ji', 'join giữ stable/all, ingest + truy vấn X'), ('q30', 'chỉ truy vấn X, R_max = 30')):
        got = [(var, s) for var in VARS for s in seeds if R(kind, var, s)]
        if got:
            print(f'\n  Biến thể bổ sung: {lab}')
            for var in VARS:
                v = [(R(kind, var, s) or {}).get('recall_at_5') for s in seeds]
                if any(x is not None for x in v):
                    rr = msd([(R(kind, var, s) or {}).get('rpc_routing_mean') for s in seeds])[0]
                    print(f"    {var:13s} Final {f1(msd(v)[0])}  so với main {fmt_pair(paired(base_new, v))}  Rout. {f1(rr, 7, 0)}")

    print('\n  C2. Dựng mạng và vị trí record theo biến thể (trung bình các seed)')
    print(f"  {'biến thể':13s} {'đặt đúng peer gần nhất':>22s} {'hạng XOR TB':>11s} {'hạng p90':>8s} "
          f"{'bảng chứa 20 gần nhất':>21s} {'contact/peer':>12s} {'RPC/ingest':>10s} {'%ingest chạm R_max':>18s} {'RPC/join':>8s}")
    for var in VARS:
        rs = [(R('main', 'stable-all', s) if var == 'stable-all' else R('b', var, s)) for s in seeds]
        rs = [r for r in rs if r]

        def g(k, sub=None):
            if sub:
                return msd([((r.get('lookup_stats') or {}).get(sub) or {}).get(k) for r in rs])[0]
            return msd([r.get(k) for r in rs])[0]
        ex = g('placement_exact_frac')
        cov = g('overlay_near20_frac')
        print(f"  {var:13s} {f1(100 * ex if ex is not None else None, 21)}% {f1(g('placement_rank_mean'), 11)} "
              f"{f1(g('placement_rank_p90'), 8)} {f1(100 * cov if cov is not None else None, 20)}% "
              f"{f1(g('overlay_contacts_mean'), 12)} {f1(g('mean_rpcs', 'ingest'), 10)} "
              f"{f1(100 * (g('frac_cap', 'ingest') or 0), 17)}% {f1(g('mean_rpcs', 'join'), 8)}")

    print('\n  C3. Mục 2.2 trên lần chạy mới: tỉ lệ lookup TRUY VẤN dừng vì chạm R_max, và lý do dừng')
    for var in VARS:
        rs = [(R('main', 'stable-all', s) if var == 'stable-all' else R('q', var, s)) for s in seeds]
        q = [((r or {}).get('lookup_stats') or {}).get('query') for r in rs]
        q = [x for x in q if x]
        if q:
            print(f"    {var:13s} chạm R_max {100 * st.mean(x['frac_cap'] for x in q):5.1f}% | frontier ổn định "
                  f"{100 * st.mean(x['frac_stable'] for x in q):5.1f}% | hết peer {100 * st.mean(x['frac_empty'] for x in q):5.1f}% "
                  f"| vòng TB {st.mean(x['mean_rounds'] for x in q):5.2f}")


# ======================================================================= phần D
def part_d(out):
    header('D. MỤC 2.4: AVAILABILITY (main_churn_test.py), k-bucket có join và seed, so với ring')
    ddir = os.path.join(out, 'D')
    res = defaultdict(dict)        # (topo, r) -> seed -> {loss: (meta, pay)}
    for p in glob.glob(os.path.join(ddir, '*_r*_s*.json')):
        d = load(p)
        if not d:
            continue
        m = re.search(r'^(\w+?)_r(\d+)_s(\d+)\.json$', os.path.basename(p))
        topo, r, s = m.group(1), int(m.group(2)), int(m.group(3))
        res[(topo, r)][s] = {int(round(100 * x['loss'])): (x['metadata'], x['payload']) for x in d['rows']}
    if not res:
        print('  chưa có kết quả nhóm D')
        return
    print(f"  {'overlay':8s} {'r':>2s} {'mất':>4s} {'n':>2s} {'metadata':>16s} {'payload':>16s}   bài in (metadata / payload)")
    for topo in ('kbucket', 'ring'):
        for r in (1, 2, 3):
            seeds = res.get((topo, r), {})
            if not seeds:
                continue
            for loss in (0, 10, 20, 30):
                me = msd([seeds[s].get(loss, (None, None))[0] for s in seeds])
                pa = msd([seeds[s].get(loss, (None, None))[1] for s in seeds])
                pp = PAPER_T9.get((r, loss))
                ptxt = f'{pp[2]:.1f} / {pp[3]:.1f}' if pp else ''
                print(f"  {topo:8s} {r:2d} {loss:3d}% {me[2]:2d} {f1(me[0])} ± {f1(me[1], 5)}   "
                      f"{f1(pa[0])} ± {f1(pa[1], 5)}   {ptxt}")
    common = defaultdict(list)
    for r in (1, 2, 3):
        a, b = res.get(('kbucket', r), {}), res.get(('ring', r), {})
        for s in sorted(set(a) & set(b)):
            for loss in (0, 10, 20, 30):
                if loss in a[s] and loss in b[s]:
                    common[(r, loss)].append((b[s][loss], a[s][loss]))
    if common:
        print('\n  k-bucket trừ ring trên cùng seed (điểm phần trăm):')
        for (r, loss), v in sorted(common.items()):
            dm = st.mean(x[1][0] - x[0][0] for x in v)
            dp = st.mean(x[1][1] - x[0][1] for x in v)
            print(f"    r={r} mất {loss:2d}%: metadata {dm:+6.1f}  payload {dp:+6.1f}  (n={len(v)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--out', default='ppna_r1/out_verify_s2')
    ap.add_argument('--vn', default='ppna_r1/out_verify_norm')
    ap.add_argument('--parts', default='ABCD')
    a = ap.parse_args()
    if 'A' in a.parts:
        part_a(a.root, a.vn)
    if 'B' in a.parts:
        part_b(a.root, a.out)
    if 'C' in a.parts:
        part_c(a.root, a.out)
    if 'D' in a.parts:
        part_d(a.out)


if __name__ == '__main__':
    main()
