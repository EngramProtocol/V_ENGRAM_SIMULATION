"""Tổng hợp đợt 3: phần iterative còn lại.

    python3 ppna_r1/dot3/aggregate.py --out-root ppna_r1/out_dot3 \
        --summary ppna_r1/dot3_summary.json > ppna_r1/dot3_report.txt
    python3 ppna_r1/dot3/aggregate.py --smoke-check ppna_r1/logs_dot3/smoke/out

Quy ước như đợt 1 và 2: mean ± SD qua seed; KTC 95% theo phân phối t; so ghép cặp theo
seed. Đọc thêm ppna_r1/out_dot2 (đợt 2) và ppna_r1/out_dot1 (mô hình lý tưởng) để so
cùng seed. Dòng cuối: "KẾT LUẬN: k vấn đề".
"""
import argparse
import collections
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A2 = _load('dot2_aggregate', os.path.join(HERE, '..', 'dot2', 'aggregate.py'))
JB = _load('dot3_jobs', os.path.join(HERE, 'jobs.py'))
A1 = A2.A1
SEEDS = JB.SEEDS
summ, paired, fm, fmean, fp, head, Store = A1.summ, A1.paired, A1.fm, A1.fmean, A1.fp, A1.head, A1.Store
var, iv, nested, mean_of = A2.var, A2.iv, A2.nested, A2.mean_of
R5, PEER, PPCT, RPC, RRT, REV, ROUNDS, TRUEK = A2.R5, A2.PEER, A2.PPCT, A2.RPC, A2.RRT, A2.REV, A2.ROUNDS, A2.TRUEK
PROBLEMS = []
SUMMARY = collections.OrderedDict()


def problem(msg):
    PROBLEMS.append(msg)
    print(f'  *** VẤN ĐỀ: {msg}')


def ideal(st1, group, name, f):
    return [None] * len(SEEDS) if st1 is None else st1.vals(group, name, f)


def ratio(a, b):
    r = [x / y for x, y in zip(a, b) if x is not None and y]
    return mean_of(r) if r else None


# ------------------------------------------------------------------ 0. đầy đủ
def completeness(st):
    head('0. ĐẦY ĐỦ VÀ PHIÊN BẢN')
    jobs = JB.build()
    by_g = collections.defaultdict(list)
    for j in jobs:
        by_g[j['group']].append(j)
    commits = collections.Counter(st.commit.values())
    print(f'  {len(st.d)} file kết quả, commit: {dict(commits)}')
    if len(commits) > 1:
        problem(f'kết quả đến từ {len(commits)} commit khác nhau')
    for g, js in by_g.items():
        miss = [j['id'] for j in js if j['id'] not in st.d]
        print(f'  {g:5s} {len(js) - len(miss):4d}/{len(js):<4d} {JB.GROUPS.get(g, "")}')
        if miss:
            problem(f'nhóm {g} thiếu {len(miss)} kết quả, ví dụ {miss[:4]}')
    it = [d for d in st.d.values() if isinstance(d, dict) and 'variants' in d]
    envs = collections.Counter(json.dumps(d.get('env'), sort_keys=True) for d in it)
    nq = collections.Counter(d.get('n_query') for d in it)
    print(f'  {len(it)} file, {sum(len(d["variants"]) for d in it)} biến thể | cấu hình chung: '
          f'{len(envs)} kiểu | số query: {dict(nq)}')
    if len(envs) > 1:
        problem('các job chạy với cấu hình môi trường khác nhau')


# ------------------------------------------------------------------ 1. hồi quy
def regression(st, st2):
    head('1. HỒI QUY: base của nhóm tk phải trùng từng số với base của nhóm sem ở đợt 2 (cùng seed)')
    if st2 is None:
        problem('không thấy kết quả đợt 2: bỏ phần hồi quy')
        return
    cnt = collections.Counter()
    nf = 0
    for s in SEEDS:
        a, b = var(st2, 'sem', 'code', 'base', s), var(st, 'tk', 'code', 'base', s)
        if a is None or b is None:
            continue
        old = {k: v for k, v in a.items() if k != 'seconds'}
        kind, bad = A2._same(old, b)
        nf = max(nf, len(old))
        cnt[kind] += 1
        if kind != 'same':
            print(f'  {kind} s{s}: ' + ', '.join(f'{k} {x} -> {y}' for k, x, y, _ in bad[:5]))
    n = sum(cnt.values())
    print(f'  {cnt["same"]}/{n} seed trùng từng số ({nf} trường), {cnt["near"]} chỉ khác ở mức làm tròn, '
          f'{cnt["diff"]} lệch')
    if cnt['diff']:
        problem(f'{cnt["diff"]} seed: base của đợt 3 lệch đợt 2')
    SUMMARY['regression_dot2'] = dict(cnt)


# ------------------------------------------------------------------ 2. Bảng 5
TK = [('base', 'T = 8, K = 20 (cấu hình chính)', ('t4', 'code_semantic')),
      ('T1_K20', 'T = 1, K = 20', ('t5', 'code_T1_K20')),
      ('T3_K20', 'T = 3, K = 20', ('t5', 'code_T3_K20')),
      ('T5_K20', 'T = 5, K = 20', ('t5', 'code_T5_K20')),
      ('T12_K20', 'T = 12, K = 20', ('t5', 'code_T12_K20')),
      ('T8_K10', 'T = 8, K = 10', ('t5', 'code_T8_K10')),
      ('T8_K40', 'T = 8, K = 40', ('t5', 'code_T8_K40')),
      ('T8_K80', 'T = 8, K = 80', ('t5', 'code_T8_K80'))]


def table5(st, st1):
    head('2. BẢNG 5 TRÊN MÔ HÌNH ITERATIVE (code, 10 seed), so với mô hình lý tưởng cùng seed')
    print(f'    {"":30s} {"R@5 iterative":>14s} {"peer %":>7s} {"RPC (routing + đánh giá)":>26s} '
          f'{"R@5 lý tưởng":>13s} {"tỉ lệ":>6s}')
    out = {}
    for vn, lab, (g1, n1) in TK:
        r5 = iv(st, 'tk', 'code', vn, R5)
        idl = ideal(st1, g1, n1, lambda d: d['recall5'])
        rr = ratio(r5, idl)
        print(f'    {lab:30s} {fm(summ(r5)):>14s} {fmean(summ(iv(st, "tk", "code", vn, PPCT)), 2):>7s} '
              f'{fmean(summ(iv(st, "tk", "code", vn, RPC)), 0):>8s} ({fmean(summ(iv(st, "tk", "code", vn, RRT)), 0)} + '
              f'{fmean(summ(iv(st, "tk", "code", vn, REV)), 0)}) {fm(summ(idl)):>13s} '
              f'{rr if rr is None else round(rr, 3)!s:>6s}')
        out[vn] = {'iter': summ(r5), 'ideal': summ(idl), 'ratio': rr,
                   'iter_minus_ideal': paired(r5, idl)}
    SUMMARY['table5_iterative'] = out


# ------------------------------------------------------------------ 3. 50.000 peer
def scale(st, st2, st1):
    head('3. 50.000 PEER TRÊN MÔ HÌNH ITERATIVE (code100k, 10 seed) và tỉ lệ iterative / lý tưởng theo N')
    out = {}
    for K in (100, 20):
        r5 = iv(st, 'ws50', 'code100k_N50000', f'K{K}', R5)
        idl = ideal(st1, 'ws', f'code100k_N50000_K{K}_semantic', lambda d: d['recall5'])
        print(f'  K = {K}: iterative {fm(summ(r5))} | lý tưởng {fm(summ(idl))} | iterative − lý tưởng '
              f'{fp(paired(r5, idl))}')
        print(f'    peer {fmean(summ(iv(st, "ws50", "code100k_N50000", f"K{K}", PPCT)), 2)}% | RPC '
              f'{fmean(summ(iv(st, "ws50", "code100k_N50000", f"K{K}", RPC)), 0)} | vòng mỗi lookup '
              f'{fmean(summ(iv(st, "ws50", "code100k_N50000", f"K{K}", ROUNDS)), 2)} | lookup < K '
              f'{fmean(summ(iv(st, "ws50", "code100k_N50000", f"K{K}", A2.SHORT)), 2)}%')
        out[f'K{K}'] = {'iter': summ(r5), 'ideal': summ(idl), 'diff': paired(r5, idl)}
    print('  tỉ lệ iterative / lý tưởng (cùng seed):')
    rows = [('10.000', 'K = N/500 = 20', iv(st2, 'sem', 'code', 'base', R5) if st2 else [None] * 10,
             ideal(st1, 't4', 'code_semantic', lambda d: d['recall5'])),
            ('25.000', 'K = N/500 = 50', iv(st2, 'ws', 'code50k_N25000', 'K50', R5) if st2 else [None] * 10,
             ideal(st1, 'ws', 'code50k_N25000_K50_semantic', lambda d: d['recall5'])),
            ('50.000', 'K = N/500 = 100', iv(st, 'ws50', 'code100k_N50000', 'K100', R5),
             ideal(st1, 'ws', 'code100k_N50000_K100_semantic', lambda d: d['recall5'])),
            ('25.000', 'K = 20', iv(st2, 'ws', 'code50k_N25000', 'K20', R5) if st2 else [None] * 10,
             ideal(st1, 'ws', 'code50k_N25000_K20_semantic', lambda d: d['recall5'])),
            ('50.000', 'K = 20', iv(st, 'ws50', 'code100k_N50000', 'K20', R5),
             ideal(st1, 'ws', 'code100k_N50000_K20_semantic', lambda d: d['recall5']))]
    for n, lab, a, b in rows:
        rr = ratio(a, b)
        print(f'    N = {n:7s} {lab:16s} iterative {fm(summ(a)):>12s} | lý tưởng {fm(summ(b)):>12s} | '
              f'tỉ lệ {"—" if rr is None else f"{rr:.3f}"}')
        out[f'ratio_{n}_{lab}'] = rr
    SUMMARY['scale_50k'] = out


# ------------------------------------------------------------------ 4. R1-4
def workloads(st, st1):
    head('4. WORKLOAD R1-4 TRÊN MÔ HÌNH ITERATIVE (10 seed): semantic và random equal peers')
    out = {}
    print(f'    {"":12s} {"semantic iter":>14s} {"lý tưởng":>12s} {"tỉ lệ":>6s} | {"random eq. iter":>15s} '
          f'{"lý tưởng":>10s} | {"semantic − control (iter)":>34s} | Gini')
    for ds, _pq in JB.WORKLOADS:
        a = iv(st, 'wl', ds, 'base', R5)
        c = iv(st, 'wl', ds, 'ctl_random_unique', R5)
        ia = ideal(st1, 'r14', f'{ds}_semantic', lambda d: d['recall5'])
        ic = ideal(st1, 'r14', f'{ds}_random_unique', lambda d: d['recall5'])
        g = summ(iv(st, 'wl', ds, 'base', lambda v: v['metadata_gini']))
        rr = ratio(a, ia)
        p = paired(a, c)
        print(f'    {ds:12s} {fm(summ(a)):>14s} {fm(summ(ia)):>12s} {"—" if rr is None else f"{rr:.3f}":>6s} | '
              f'{fm(summ(c)):>15s} {fm(summ(ic)):>10s} | {fp(p):>34s} | {fmean(g, 2)}')
        out[ds] = {'semantic': summ(a), 'ideal': summ(ia), 'ratio': rr, 'control': summ(c),
                   'semantic_minus_control': p}
    SUMMARY['workloads_iterative'] = out


# ------------------------------------------------------------------ 5. làm mới bucket
def refresh(st, st2, st1):
    head('5. JOIN ĐẦY ĐỦ NHƯ KADEMLIA GỐC: vòng làm mới k-bucket sau join (10 seed)')
    out = {}
    for ds in ('code', 'scifact'):
        rows = []
        base = iv(st2, 'sem', ds, 'base', R5) if st2 else [None] * 10
        rows.append(('chỉ join (đợt 2)', base, ('sem', ds, 'base', st2)))
        for r in (1, 2):
            rows.append((f'join + {r} vòng làm mới', iv(st, 'ref', ds, f'refresh{r}_base', R5),
                         ('ref', ds, f'refresh{r}_base', st)))
        full = iv(st2, 'dec', ds, 'Pr_Tf_Qr', R5) if st2 else [None] * 10
        rows.append(('bảng đầy đủ (đợt 2)', full, ('dec', ds, 'Pr_Tf_Qr', st2)))
        oo = iv(st2, 'dec', ds, 'Po_Tf_Qo', R5) if st2 else [None] * 10
        idl = ideal(st1, 't4', f'{ds}_semantic', lambda d: d['recall5'])
        print(f'  {ds}:')
        print(f'    {"":26s} {"R@5":>12s} {"contact/peer":>13s} {"20 gần nhất":>11s} {"đặt đúng":>9s} '
              f'{"RPC":>6s} {"vòng":>5s} {"trùng K thật":>12s}')
        for lab, r5, (g, j, vn, src) in rows:
            if src is None:
                continue
            cm = summ(iv(src, g, j, vn, lambda v: v['overlay_contacts_mean']))
            nn = summ(iv(src, g, j, vn, lambda v: 100 * v['overlay_near20_frac']))
            pe = summ(iv(src, g, j, vn, lambda v: 100 * v['placement_exact_frac']))
            print(f'    {lab:26s} {fm(summ(r5)):>12s} {fmean(cm, 1):>13s} {fmean(nn, 1):>10s}% {fmean(pe, 1):>8s}% '
                  f'{fmean(summ(iv(src, g, j, vn, RPC)), 0):>6s} {fmean(summ(iv(src, g, j, vn, ROUNDS)), 2):>5s} '
                  f'{fmean(summ(iv(src, g, j, vn, TRUEK)), 1):>11s}%')
        print(f'    toàn oracle (đợt 2) {fm(summ(oo))} | mô hình lý tưởng (đợt 1) {fm(summ(idl))}')
        r1 = iv(st, 'ref', ds, 'refresh1_base', R5)
        r2 = iv(st, 'ref', ds, 'refresh2_base', R5)
        gain = paired(r1, base)
        rest = paired(oo, r1)
        gap = paired(oo, base)
        print(f'    làm mới 1 vòng − chỉ join: {fp(gain)}')
        print(f'    toàn oracle − làm mới 1 vòng (phần còn lại): {fp(rest)}')
        print(f'    vòng 2 − vòng 1: {fp(paired(r2, r1))}')
        if gain and gap and gap['mean']:
            print(f'    một vòng làm mới lấy lại {100 * gain["mean"] / gap["mean"]:.0f}% khoảng cách '
                  f'{gap["mean"]:.2f} điểm')
        fb = iv(st, 'ref', ds, 'refresh1_t7_exhaust-all_R15', R5)
        print(f'    sau làm mới, frontier stability − full round budget: {fp(paired(r1, fb))} | RPC '
              f'{fmean(summ(iv(st, "ref", ds, "refresh1_base", RPC)), 0)} so với '
              f'{fmean(summ(iv(st, "ref", ds, "refresh1_t7_exhaust-all_R15", RPC)), 0)}')
        qo = iv(st, 'ref', ds, 'refresh1_q_oracle', R5)
        print(f'    sau làm mới, truy vấn oracle − Ripple Search: {fp(paired(qo, r1))}')
        lk = []
        for s in SEEDS:
            d = st.get('ref', ds, s)
            if d and 'refresh' in d:
                lk.append(d['refresh']['1']['lookups'] / d['nodes'])
        if lk:
            print(f'    chi phí làm mới: {mean_of(lk):.1f} lookup mỗi peer mỗi vòng')
        out[ds] = {'refresh1': summ(r1), 'refresh2': summ(r2), 'gain': gain, 'remaining': rest,
                   'gap_join_only': gap}
    SUMMARY['refresh'] = out


# ------------------------------------------------------------------ 6. Bucket-LSH nhạy
def bucket_full(st, st2, st1):
    head('6. BUCKET-LSH VỚI INGEST CHẠY HẾT NGÂN SÁCH (exhaust/all, R_max 15), T = 8, b theo seed')
    out = {}
    for ds in ('code', 'scifact'):
        bs = JB.B_LSH_T8[ds]
        f = [var(st, 'lshf', f'{ds}_T8', f'bucket_b{bs[i]}_T8', s) for i, s in enumerate(SEEDS)]
        n = [var(st2, 'lsh', f'{ds}_T8', f'bucket_b{bs[i]}_T8', s) if st2 else None
             for i, s in enumerate(SEEDS)]
        rf = [v and v['recall_at_5'] for v in f]
        rn = [v and v['recall_at_5'] for v in n]
        pe = [v and 100 * v['placement_exact_frac'] for v in f]
        il5 = []
        for i, s in enumerate(SEEDS):
            d1 = st1.get('lsh', f'{ds}_T8_test', s) if st1 is not None else None
            w = {x['b']: x for x in d1['widths']} if d1 else {}
            il5.append(w[bs[i]]['recall5'] if bs[i] in w else None)
        vf = iv(st2, 'dec', ds, 'Pfull_Tj_Qr', R5) if st2 else [None] * 10
        vb = iv(st2, 'sem', ds, 'base', R5) if st2 else [None] * 10
        print(f'  {ds}: Bucket-LSH ingest thường {fm(summ(rn))} | ingest hết ngân sách {fm(summ(rf))} '
              f'(đặt đúng {fmean(summ(pe), 1)}%) | lý tưởng cùng b {fm(summ(il5))}')
        print(f'    ingest hết ngân sách − ingest thường: {fp(paired(rf, rn))}')
        print(f'    V-Engram − Bucket-LSH, cả hai ingest thường: {fp(paired(vb, rn))}')
        print(f'    V-Engram − Bucket-LSH, cả hai ingest hết ngân sách: {fp(paired(vf, rf))}')
        print(f'    Bucket-LSH iterative (ingest hết ngân sách) − lý tưởng: {fp(paired(rf, il5))}')
        out[ds] = {'bucket_normal': summ(rn), 'bucket_full': summ(rf), 'vengram_full': summ(vf),
                   'gap_full': paired(vf, rf), 'gap_normal': paired(vb, rn)}
    SUMMARY['bucket_lsh_full_ingest'] = out


def _row(lab, plain, full, idl, out, key):
    """In một hàng so join cũ với join đầy đủ (và mô hình lý tưởng nếu có)."""
    d = paired(full, plain)
    di = paired(full, idl)
    rr = ratio(full, idl)
    print(f'    {lab:34s} {fm(summ(plain)):>12s} {fm(summ(full)):>12s} {fm(summ(idl)):>12s} | '
          f'{fp(d)} | đầy đủ − lý tưởng {fp(di)} | tỉ lệ {"—" if rr is None else f"{rr:.3f}"}')
    out[key] = {'plain': summ(plain), 'full_join': summ(full), 'ideal': summ(idl),
                'full_minus_plain': d, 'full_minus_ideal': di, 'ratio_full_ideal': rr}


def replica(st, st2, st1):
    head('8. BẢN SAO VỚI JOIN ĐẦY ĐỦ (join + một vòng làm mới k-bucket), 10 seed: cột "cũ" là join của '
         'bản đã nộp, cột "đầy đủ" là join như Kademlia gốc')
    out = collections.OrderedDict()
    if st2 is None:
        problem('không thấy kết quả đợt 2: bỏ phần bản sao')
        return
    # kiểm chéo: base của sem_r phải trùng refresh1_base của nhóm ref (cùng mạng, cùng số ngẫu nhiên)
    same = tot = 0
    for ds in ('code', 'scifact'):
        for s in SEEDS:
            a, b = var(st, 'sem_r', ds, 'base', s), var(st, 'ref', ds, 'refresh1_base', s)
            if a is None or b is None:
                continue
            tot += 1
            same += (a['per_query_hits5'] == b['per_query_hits5'] and a['mean_rpcs'] == b['mean_rpcs'])
    print(f'  kiểm chéo: base của sem_r trùng refresh1_base của nhóm ref ở {same}/{tot} cặp seed, corpus')
    if same != tot:
        problem(f'{tot - same} cặp: base của join đầy đủ lệch refresh1_base')
    hdr = f'    {"":34s} {"cũ":>12s} {"đầy đủ":>12s} {"lý tưởng":>12s} | đầy đủ − cũ'
    for ds in ('code', 'scifact'):
        print(f'  {ds}: Bảng 7, control, ablation (R@5)')
        print(hdr)
        idl = ideal(st1, 't4', f'{ds}_semantic', lambda d: d['recall5'])
        rows = [('base', 'cấu hình chính', idl),
                ('t7_exhaust-topk_R15', 'exhaustive top-K', None),
                ('t7_exhaust-all_R15', 'full round budget, R_max 15', None),
                ('t7_exhaust-all_R30', 'full round budget, R_max 30', None),
                ('q_oracle', 'truy vấn oracle', None),
                ('ctl_random_unique', 'random equal peers', ideal(st1, 't4', f'{ds}_random_unique', lambda d: d['recall5'])),
                ('ctl_random_keys', 'random keyed', ideal(st1, 't4', f'{ds}_random_keys', lambda d: d['recall5'])),
                ('ctl_random_slots', 'random nominal', ideal(st1, 't4', f'{ds}_random_slots', lambda d: d['recall5'])),
                ('ctl_random_equalcand', 'random candidate threshold', ideal(st1, 't4', f'{ds}_random_equalcand', lambda d: d['recall5'])),
                ('abl_random_order', 'lật bit ngẫu nhiên', None),
                ('c9_T5', 'c = 9, T = 5', ideal(st1, 'r11', f'{ds}_c9_T5_semantic', lambda d: d['recall5']))]
        for vn, lab, ii in rows:
            _row(lab, iv(st2, 'sem', ds, vn, R5), iv(st, 'sem_r', ds, vn, R5),
                 ii if ii is not None else [None] * len(SEEDS), out, f'{ds}/{vn}')
        b, fb = iv(st, 'sem_r', ds, 'base', R5), iv(st, 'sem_r', ds, 't7_exhaust-all_R15', R5)
        rb, rf = iv(st, 'sem_r', ds, 'base', RPC), iv(st, 'sem_r', ds, 't7_exhaust-all_R15', RPC)
        sv = [1 - x / y for x, y in zip(rb, rf) if x is not None and y]
        print(f'    join đầy đủ: frontier stability − full round budget {fp(paired(b, fb))}, ít RPC hơn '
              f'{100 * mean_of(sv) if sv else float("nan"):.1f}% | RPC cấu hình chính '
              f'{fmean(summ(iv(st2, "sem", ds, "base", RPC)), 0)} (cũ) -> {fmean(summ(rb), 0)} (đầy đủ)')
        for c in ('ctl_random_unique', 'ctl_random_keys', 'ctl_random_slots', 'ctl_random_equalcand'):
            print(f'    join đầy đủ: semantic − {c[4:]}: {fp(paired(b, iv(st, "sem_r", ds, c, R5)))}')
        print(f'    join đầy đủ: margin − ngẫu nhiên {fp(paired(b, iv(st, "sem_r", ds, "abl_random_order", R5)))} | '
              f'c9 T5 − c16 T8 {fp(paired(iv(st, "sem_r", ds, "c9_T5", R5), b))}')
        # Bucket-LSH
        bs = JB.B_LSH_T8[ds]
        lp = [(var(st2, 'lsh', f'{ds}_T8', f'bucket_b{bs[i]}_T8', s) or {}).get('recall_at_5') for i, s in enumerate(SEEDS)]
        lf = [(var(st, 'lsh_r', f'{ds}_T8', f'bucket_b{bs[i]}_T8', s) or {}).get('recall_at_5') for i, s in enumerate(SEEDS)]
        print(f'    Bucket-LSH: cũ {fm(summ(lp))} | đầy đủ {fm(summ(lf))} | V-Engram − Bucket-LSH: cũ '
              f'{fp(paired(iv(st2, "sem", ds, "base", R5), lp))}; đầy đủ {fp(paired(b, lf))}')
        out[f'{ds}/bucket_gap_full'] = paired(b, lf)
    print('  code: mất peer (R@5)')
    print(hdr)
    for lab, (g2, j2, v2), (g3, j3, v3), (g1, n1) in (
            ('r = 1, mất 20%', ('sem', 'code', 'loss0.20'), ('sem_r', 'code', 'loss0.20'), ('loss', 'code_r1_loss0.20')),
            ('r = 1, mất 30%', ('sem', 'code', 'loss0.30'), ('sem_r', 'code', 'loss0.30'), ('loss', 'code_r1_loss0.30')),
            ('r = 2, không mất', ('loss', 'code_r23', 'r2_loss0.00'), ('loss_r', 'code_r23', 'r2_loss0.00'), ('t8', 'code_r2_semantic')),
            ('r = 2, mất 30%', ('loss', 'code_r23', 'r2_loss0.30'), ('loss_r', 'code_r23', 'r2_loss0.30'), ('loss', 'code_r2_loss0.30')),
            ('r = 3, không mất', ('loss', 'code_r23', 'r3_loss0.00'), ('loss_r', 'code_r23', 'r3_loss0.00'), ('loss', 'code_r3_loss0.00')),
            ('r = 3, mất 30%', ('loss', 'code_r23', 'r3_loss0.30'), ('loss_r', 'code_r23', 'r3_loss0.30'), ('loss', 'code_r3_loss0.30'))):
        _row(lab, iv(st2, g2, j2, v2, R5), iv(st, g3, j3, v3, R5), ideal(st1, g1, n1, lambda d: d['recall5']),
             out, f'loss/{lab}')
    print('  code: quy mô (R@5)')
    print(hdr)
    for lab, plain, full, (g1, n1) in (
            ('25.000 peer, K = 50', iv(st2, 'ws', 'code50k_N25000', 'K50', R5), iv(st, 'ws25_r', 'code50k_N25000', 'K50', R5),
             ('ws', 'code50k_N25000_K50_semantic')),
            ('25.000 peer, K = 20', iv(st2, 'ws', 'code50k_N25000', 'K20', R5), iv(st, 'ws25_r', 'code50k_N25000', 'K20', R5),
             ('ws', 'code50k_N25000_K20_semantic')),
            ('50.000 peer, K = 100', iv(st, 'ws50', 'code100k_N50000', 'K100', R5), iv(st, 'ws50_r', 'code100k_N50000', 'K100', R5),
             ('ws', 'code100k_N50000_K100_semantic')),
            ('50.000 peer, K = 20', iv(st, 'ws50', 'code100k_N50000', 'K20', R5), iv(st, 'ws50_r', 'code100k_N50000', 'K20', R5),
             ('ws', 'code100k_N50000_K20_semantic'))):
        _row(lab, plain, full, ideal(st1, g1, n1, lambda d: d['recall5']), out, f'scale/{lab}')
    print('  code: Bảng 5 (R@5)')
    print(hdr)
    for vn, lab, (g1, n1) in TK:
        _row(lab, iv(st, 'tk', 'code', vn, R5), iv(st, 'tk_r', 'code', vn, R5),
             ideal(st1, g1, n1, lambda d: d['recall5']), out, f'tk/{vn}')
    print('  workload R1-4 (R@5 semantic)')
    print(hdr)
    for ds, _pq in JB.WORKLOADS:
        _row(ds, iv(st, 'wl', ds, 'base', R5), iv(st, 'wl_r', ds, 'base', R5),
             ideal(st1, 'r14', f'{ds}_semantic', lambda d: d['recall5']), out, f'wl/{ds}')
    SUMMARY['full_join_replica'] = out


def timing(st):
    head('7. THỜI GIAN VÀ BỘ NHỚ')
    by, rss = collections.defaultdict(list), collections.defaultdict(list)
    for k, d in st.d.items():
        if isinstance(d, dict) and 'timing' in d:
            g = k.split('/')[0] + '/' + k.split('/')[1].rsplit('_s', 1)[0]
            by[g].append(d['timing'].get('total', 0))
            rss[g].append(d.get('peak_rss_mb', 0))
    for g in sorted(by):
        print(f'  {g:24s} {len(by[g]):3d} job | TB {sum(by[g]) / len(by[g]) / 60:6.1f} phút | '
              f'RSS đỉnh lớn nhất {max(rss[g]):6.0f} MB')


def smoke_check(root):
    jobs = JB.build_smoke()
    need = {'tk': ['base', 'T1_K20', 'T12_K20', 'T8_K80'], 'ws': ['K100', 'K20'],
            'refresh': ['refresh1_base', 'refresh2_q_oracle', 'refresh1_t7_exhaust-all_R15'],
            'lsh': ['bucket_b10_T8'], 'wl': ['base', 'ctl_random_unique'],
            'sem': ['base', 't7_exhaust-all_R30', 'ctl_random_equalcand', 'q_oracle', 'loss0.30']}
    bad = 0
    for j in jobs:
        p = j['out'].replace('ppna_r1/logs_dot3/smoke/out', root, 1)
        err = []
        try:
            with open(p, encoding='utf-8') as fh:
                d = json.load(fh)
        except Exception as e:  # noqa: BLE001
            print(f'  LỖI {j["id"]}: không đọc được {p} ({e})')
            bad += 1
            continue
        plan = j['cmd'][j['cmd'].index('--plan') + 1]
        vs = d.get('variants', {})
        err += [f'thiếu biến thể {x}' for x in need[plan] if x not in vs]
        err += [f'{n}: thiếu recall' for n, v in vs.items() if v.get('recall_at_5') is None]
        if plan == 'refresh' and len(d.get('refresh', {})) != 2:
            err.append('thiếu thống kê vòng làm mới')
        if plan == 'lsh' and not str(list(d.get('stages', {}).values())[0].get('ingest_rule', '')).startswith('exhaust'):
            err.append('ingest không chạy exhaust')
        if 'jina' in j['id'] and d.get('dim') != 896:
            err.append(f'dim {d.get("dim")} khác 896')
        if '--join-refresh' in j['cmd'] and '1' not in d.get('join_refresh', {}):
            err.append('thiếu thống kê join đầy đủ')
        if err:
            bad += 1
            print(f'  LỖI {j["id"]}: {"; ".join(err[:6])}')
        else:
            print(f'  đạt {j["id"]}')
    print(f'SMOKE CHECK: {len(jobs) - bad}/{len(jobs)} đạt')
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-root', default='ppna_r1/out_dot3')
    ap.add_argument('--dot2-root', default='ppna_r1/out_dot2')
    ap.add_argument('--dot1-root', default='ppna_r1/out_dot1')
    ap.add_argument('--summary', default=None)
    ap.add_argument('--smoke-check', default=None, metavar='DIR')
    a = ap.parse_args()
    if a.smoke_check:
        return smoke_check(a.smoke_check)
    st = Store(a.out_root)
    st2 = Store(a.dot2_root) if os.path.isdir(a.dot2_root) else None
    st1 = Store(a.dot1_root) if os.path.isdir(a.dot1_root) else None
    print(f'TỔNG HỢP ĐỢT 3 | {len(st.d)} file trong {a.out_root} | đợt 2: {len(st2.d) if st2 else 0} file | '
          f'đợt 1: {len(st1.d) if st1 else 0} file')
    if st2 is None:
        problem(f'không thấy {a.dot2_root}')
    if st1 is None:
        problem(f'không thấy {a.dot1_root}')
    completeness(st)
    regression(st, st2)
    for fn, args in ((table5, (st, st1)), (scale, (st, st2, st1)), (workloads, (st, st1)),
                     (refresh, (st, st2, st1)), (bucket_full, (st, st2, st1)), (replica, (st, st2, st1)),
                     (timing, (st,))):
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            problem(f'{fn.__name__} lỗi khi tổng hợp: {type(e).__name__}: {e}')
    if a.summary:
        with open(a.summary, 'w', encoding='utf-8') as fh:
            json.dump(SUMMARY, fh, indent=1, ensure_ascii=False, default=str)
    print()
    print(f'KẾT LUẬN: {len(PROBLEMS)} vấn đề')
    for p in PROBLEMS:
        print(f'  - {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
