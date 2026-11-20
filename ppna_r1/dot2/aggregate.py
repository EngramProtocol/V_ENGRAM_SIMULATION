"""Tổng hợp đợt 2: mô hình iterative và hai phần nhỏ trên mô hình lý tưởng.

    python3 ppna_r1/dot2/aggregate.py --out-root ppna_r1/out_dot2 \
        --summary ppna_r1/dot2_summary.json > ppna_r1/dot2_report.txt
    python3 ppna_r1/dot2/aggregate.py --smoke-check ppna_r1/logs_dot2/smoke/out

Quy ước như đợt 1: mean ± SD qua seed; KTC 95% theo phân phối t; phép so ghép cặp theo
seed. Mọi kết quả phải đến từ cùng một commit. Dòng cuối: "KẾT LUẬN: k vấn đề".
Số của đợt 1 (mô hình lý tưởng) đọc từ ppna_r1/out_dot1 để so cùng seed.
"""
import argparse
import collections
import importlib.util
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOT1 = os.path.join(HERE, '..', 'dot1')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, DOT1)          # aggregate của đợt 1 import jobs và submitted của nó
A1 = _load('dot1_aggregate', os.path.join(DOT1, 'aggregate.py'))
JB = _load('dot2_jobs', os.path.join(HERE, 'jobs.py'))

SEEDS = JB.SEEDS
summ, paired, fm, fmean, fp, head, Store = A1.summ, A1.paired, A1.fm, A1.fmean, A1.fp, A1.head, A1.Store
NESTS = ((5, SEEDS[:5]), (7, SEEDS[:7]), (10, SEEDS))
PROBLEMS = []
SUMMARY = collections.OrderedDict()
DS = ('code', 'scifact')


def problem(msg):
    PROBLEMS.append(msg)
    print(f'  *** VẤN ĐỀ: {msg}')


def mean_of(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def nested(a, b):
    out = []
    for n, ss in NESTS:
        idx = [SEEDS.index(s) for s in ss]
        p = paired([a[i] for i in idx], [b[i] for i in idx])
        out.append(f'{n} seed: ' + ('—' if p is None else f'{p["mean"]:+.2f} [{p["lo"]:+.2f}, {p["hi"]:+.2f}]'))
    return ' | '.join(out)


# ------------------------------------------------------------------ truy cập dữ liệu
def var(st, group, job, name, seed):
    d = st.get(group, job, seed)
    if d is None:
        return None
    return d.get('variants', {}).get(name)


def iv(st, group, job, name, f):
    out = []
    for s in SEEDS:
        v = var(st, group, job, name, s)
        try:
            out.append(None if v is None else f(v))
        except (KeyError, TypeError, ZeroDivisionError, ValueError):
            out.append(None)
    return out


R5 = lambda v: v['recall_at_5']                                       # noqa: E731
PEER = lambda v: v['mean_contacted']                                  # noqa: E731
PPCT = lambda v: v['pct_contacted']                                   # noqa: E731
RPC = lambda v: v['mean_rpcs']                                        # noqa: E731
RRT = lambda v: v['rpc_routing_mean']                                 # noqa: E731
REV = lambda v: v['rpc_eval_mean']                                    # noqa: E731
CAND = lambda v: v['mean_candidates']                                 # noqa: E731
ROUNDS = lambda v: v['lookup_stats']['query']['mean_rounds']          # noqa: E731
CAP = lambda v: 100.0 * v['lookup_stats']['query']['frac_cap']        # noqa: E731
TRUEK = lambda v: 100.0 * v['truek_overlap_mean']                     # noqa: E731
SHORT = lambda v: 100.0 * v['short_lookup_frac']                      # noqa: E731
XR = lambda v: v['xor_rank_mean']                                     # noqa: E731
LOOKUPS = lambda v: v['lookups_total'] / v['n_query']                 # noqa: E731


def ideal(st1, group, name, f):
    if st1 is None:
        return [None] * len(SEEDS)
    return st1.vals(group, name, f)


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
    if st.incomplete:
        print(f'  {len(st.incomplete)} file chưa xong (thiếu .ok), ví dụ {st.incomplete[:3]}')
    for g, js in by_g.items():
        miss = [j['id'] for j in js if j['id'] not in st.d]
        print(f'  {g:5s} {len(js) - len(miss):4d}/{len(js):<4d} {JB.GROUPS.get(g, "")}')
        if miss:
            problem(f'nhóm {g} thiếu {len(miss)} kết quả, ví dụ {miss[:4]}')
    it = [d for d in st.d.values() if isinstance(d, dict) and 'variants' in d]
    envs = collections.Counter(json.dumps(d.get('env'), sort_keys=True) for d in it)
    nq = collections.Counter(d.get('n_query') for d in it)
    nv = sum(len(d['variants']) for d in it)
    print(f'  iterative: {len(it)} file, {nv} biến thể | cấu hình chung: {len(envs)} kiểu | số query: {dict(nq)}')
    if len(envs) > 1:
        problem('các job iterative chạy với cấu hình môi trường khác nhau')
    v2 = [d for d in st.d.values() if isinstance(d, dict) and 'recall5' in d]
    nonorm = sum(1 for d in v2 if not d.get('normalize_cols'))
    print(f'  lý tưởng: {len(v2)} file | chuẩn hoá cột {len(v2) - nonorm}/{len(v2)}')
    if nonorm:
        problem(f'{nonorm} file lý tưởng không chuẩn hoá cột')


# ------------------------------------------------------------------ 1. hồi quy
def _same(old, new, skip=()):
    """(trùng, gần, lệch) trên các trường chung. Gần: sai khác làm tròn, recall trùng."""
    bad = []
    for k in old:
        if k in skip or k not in new:
            continue
        a, b = old[k], new[k]
        if a == b:
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            rel = abs(a - b) / max(1.0, abs(a))
            if rel <= 1e-12:
                continue
            bad.append((k, a, b, rel))
        else:
            bad.append((k, a, b, None))
    if not bad:
        return 'same', bad
    if all(r is not None and r <= 1e-5 for _, _, _, r in bad) and \
            not any('recall' in k or k in ('hit_at_5', 'mrr') for k, _, _, _ in bad):
        return 'near', bad
    return 'diff', bad


def regression(st, verify_s2):
    head('1. HỒI QUY: biến thể chạy trên mạng dựng chung phải trùng từng số với lần chạy riêng '
         'của đợt kiểm 17/11 (cùng seed, cùng cấu hình)')
    pairs = [('base', 'main_stable-all'), ('t7_stable-topk_R15', 'q_stable-topk'),
             ('t7_exhaust-topk_R15', 'q_exhaust-topk'), ('t7_exhaust-all_R15', 'q_exhaust-all')]
    cnt = collections.Counter()
    nfield = 0
    for s in SEEDS:
        for vname, oname in pairs:
            p = os.path.join(verify_s2, 'C', f'{oname}_s{s}.json')
            new = var(st, 'sem', 'code', vname, s)
            if new is None or not os.path.isfile(p):
                continue
            with open(p, encoding='utf-8') as fh:
                old = json.load(fh)
            kind, bad = _same(old, new)
            cnt[kind] += 1
            nfield = max(nfield, len([k for k in old if k in new]))
            if kind == 'near':
                print(f'  sai khác làm tròn {vname} s{s}: ' +
                      ', '.join(f'{k} {a} -> {b}' for k, a, b, _ in bad[:4]))
            elif kind == 'diff':
                print(f'  LỆCH {vname} s{s}: ' + ', '.join(f'{k} {a} -> {b}' for k, a, b, _ in bad[:6]))
    n = sum(cnt.values())
    print(f'  {cnt["same"]}/{n} lần chạy trùng từng số ({nfield} trường), {cnt["near"]} chỉ khác ở mức '
          f'làm tròn, {cnt["diff"]} lệch')
    if n == 0:
        print('  (không so được: thiếu ppna_r1/out_verify_s2/C)')
    if cnt['diff']:
        problem(f'{cnt["diff"]} biến thể lệch với lần chạy riêng của đợt kiểm 17/11')
    SUMMARY['regression_17_11'] = dict(cnt)
    # kiểm nội bộ: hai ô toàn oracle (bảng join và bảng đầy đủ) phải trùng nhau
    same = diff = 0
    for ds in DS:
        for s in SEEDS:
            a, b = var(st, 'dec', ds, 'Po_Tj_Qo', s), var(st, 'dec', ds, 'Po_Tf_Qo', s)
            if a is None or b is None:
                continue
            if a['per_query_hits5'] == b['per_query_hits5'] and a['mean_contacted'] == b['mean_contacted']:
                same += 1
            else:
                diff += 1
    print(f'  ô (đặt oracle, truy vấn oracle) trên bảng join và bảng đầy đủ: {same} trùng, {diff} khác '
          f'(phải trùng: khi cả đặt record lẫn truy vấn đều oracle thì bảng định tuyến không được dùng)')
    if diff:
        problem(f'{diff} cặp ô toàn oracle khác nhau giữa hai loại bảng')


# ------------------------------------------------------------------ 2. Bảng 7
T7_ROWS = [('base', 'Frontier stability, phạm vi all peers (cấu hình chính)'),
           ('t7_stable-topk_R15', 'Frontier stability, phạm vi top-K'),
           ('t7_exhaust-topk_R15', 'Exhaustive top-K'),
           ('t7_exhaust-all_R15', 'Full round budget (R_max = 15)'),
           ('t7_exhaust-topk_R30', 'Exhaustive top-K, R_max = 30'),
           ('t7_exhaust-all_R30', 'Full round budget, R_max = 30')]


def table7(st):
    head('2. BẢNG 7 MỚI: chỉ đổi quy tắc dừng của truy vấn (join và ingest giữ stable/all, R_max = 15), 10 seed')
    out = {}
    for ds in DS:
        print(f'  {ds}')
        print(f'    {"quy tắc":48s} {"R@5":>12s} {"RPC/query":>10s} {"routing":>8s} {"đánh giá":>9s} '
              f'{"vòng/lookup":>11s} {"chạm R_max":>10s} {"trùng K thật":>12s} {"hạng XOR":>8s}')
        base_r5 = iv(st, 'sem', ds, 'base', R5)
        base_rpc = iv(st, 'sem', ds, 'base', RPC)
        rows = {}
        for vn, lab in T7_ROWS:
            r5, rpc = iv(st, 'sem', ds, vn, R5), iv(st, 'sem', ds, vn, RPC)
            row = {k: summ(iv(st, 'sem', ds, vn, f)) for k, f in
                   (('r5', R5), ('rpc', RPC), ('rrt', RRT), ('rev', REV), ('rounds', ROUNDS), ('cap', CAP),
                    ('truek', TRUEK), ('xr', XR))}
            rows[vn] = row
            print(f'    {lab:48s} {fm(row["r5"]):>12s} {fmean(row["rpc"], 0):>10s} {fmean(row["rrt"], 0):>8s} '
                  f'{fmean(row["rev"], 0):>9s} {fmean(row["rounds"], 2):>11s} {fmean(row["cap"], 1):>9s}% '
                  f'{fmean(row["truek"], 1):>11s}% {fmean(row["xr"], 1):>8s}')
            if vn != 'base':
                p = paired(base_r5, r5)
                save = [1 - b / v for b, v in zip(base_rpc, rpc) if b is not None and v]
                if p or save:
                    msg = f'      cấu hình chính − hàng này: R@5 {fp(p)}'
                    if save:
                        msg += f' | cấu hình chính dùng ít RPC hơn {100 * mean_of(save):.1f}%'
                    print(msg)
                row['diff_vs_base'] = p
                row['rpc_saving_pct'] = 100 * mean_of(save) if save else None
                if p and vn in ('t7_exhaust-all_R15', 't7_exhaust-topk_R15'):
                    print(f'      lồng nhau: {nested(base_r5, r5)}')
        out[ds] = rows
    SUMMARY['table7'] = out


# ------------------------------------------------------------------ 3. phân tách
CELLS = {  # (đặt record, bảng, truy vấn) -> (nhóm, job, biến thể); r = thật, o = oracle
    ('r', 'r', 'r'): ('sem', 'base'), ('r', 'r', 'o'): ('sem', 'q_oracle'),
    ('o', 'r', 'r'): ('dec', 'Po_Tj_Qr'), ('o', 'r', 'o'): ('dec', 'Po_Tj_Qo'),
    ('r', 'o', 'r'): ('dec', 'Pr_Tf_Qr'), ('r', 'o', 'o'): ('dec', 'Pr_Tf_Qo'),
    ('o', 'o', 'r'): ('dec', 'Po_Tf_Qr'), ('o', 'o', 'o'): ('dec', 'Po_Tf_Qo'),
}
FACT = ('đặt record', 'bảng định tuyến', 'truy vấn')


def _cell(st, ds, key):
    g, v = CELLS[key]
    return iv(st, g, ds, v, R5)


def _shapley(f):
    """f: dict khoá (p,t,q) -> giá trị. Shapley của từng yếu tố khi chuyển từ thật sang oracle."""
    out = []
    for i in range(3):
        tot = 0.0
        for S in range(8):
            if S >> i & 1:
                continue
            k = bin(S).count('1')
            w = math.factorial(k) * math.factorial(2 - k) / 6.0
            a = tuple('o' if (S >> j & 1) or j == i else 'r' for j in range(3))
            b = tuple('o' if (S >> j & 1) else 'r' for j in range(3))
            tot += w * (f[a] - f[b])
        out.append(tot)
    return out


def decomposition(st, st1):
    head('3. PHÂN TÁCH KHOẢNG CÁCH GIỮA HAI MÔ HÌNH: ba công tắc oracle, 2 × 2 × 2 ô, 10 seed')
    out = {}
    for ds in DS:
        cells = {k: _cell(st, ds, k) for k in CELLS}
        print(f'  {ds}: R@5 từng ô (r = thật, o = oracle; thứ tự đặt record / bảng / truy vấn)')
        for k in sorted(CELLS):
            print(f'    {"/".join(k)}  {fm(summ(cells[k])):>14s}   ({CELLS[k][0]}: {CELLS[k][1]})')
        ing = iv(st, 'dec', ds, 'Pfull_Tj_Qr', R5)
        print(f'    ingest chạy hết ngân sách (exhaust/all, R_max 15), bảng join, Ripple Search: {fm(summ(ing))}')
        ref = ideal(st1, 't4', f'{ds}_semantic', lambda d: d['recall5'])
        print(f'    mô hình lý tưởng (đợt 1, cùng seed): {fm(summ(ref))}')
        # độ chính xác đặt record và độ đầy bảng định tuyến
        pl = {lab: summ([None if d is None else d['stages'][lab]['placement_exact_frac'] * 100
                         for d in (st.get('dec', ds, s) for s in SEEDS)]) for lab in ('Pfull_Tj', 'Pr_Tf')}
        plm = summ([None if v is None else v['placement_exact_frac'] * 100 for v in
                    (var(st, 'sem', ds, 'base', s) for s in SEEDS)])
        cov_j = summ(iv(st, 'sem', ds, 'base', lambda v: 100 * v['overlay_near20_frac']))
        cov_f = summ([None if d is None else 100 * d['variants']['Pr_Tf_Qr']['overlay_near20_frac']
                      for d in (st.get('dec', ds, s) for s in SEEDS)])
        print(f'    record đặt đúng peer gần nhất: ingest thường {fmean(plm)}%, ingest hết ngân sách '
              f'{fmean(pl["Pfull_Tj"])}%, ingest trên bảng đầy đủ {fmean(pl["Pr_Tf"])}%')
        print(f'    bảng định tuyến chứa 20 peer gần nhất thật: join {fmean(cov_j)}%, đầy đủ {fmean(cov_f)}%')
        gap = paired(cells[('o', 'o', 'o')], cells[('r', 'r', 'r')])
        print(f'    khoảng cách (toàn oracle − toàn thật): {fp(gap)}')
        ok = [all(cells[k][i] is not None for k in CELLS) for i in range(len(SEEDS))]
        sh = [_shapley({k: cells[k][i] for k in CELLS}) if ok[i] else None for i in range(len(SEEDS))]
        main_eff, shap = {}, {}
        for i, nm in enumerate(FACT):
            on = [mean_of([cells[k][j] for k in CELLS if k[i] == 'o']) if ok[j] else None
                  for j in range(len(SEEDS))]
            off = [mean_of([cells[k][j] for k in CELLS if k[i] == 'r']) if ok[j] else None
                   for j in range(len(SEEDS))]
            main_eff[nm] = paired(on, off)
            shap[nm] = summ([None if x is None else x[i] for x in sh])
            sv = shap[nm]
            print(f'    {nm:16s} hiệu ứng chính {fp(main_eff[nm])}')
            if sv:
                print(f'    {"":16s} Shapley {sv["mean"]:+.2f} [{sv["mean"] - sv["ci95"]:+.2f}, '
                      f'{sv["mean"] + sv["ci95"]:+.2f}]')
        # tương tác hai chiều và ba chiều (tương phản của thiết kế 2^3)
        def contrast(sign):
            v = []
            for j in range(len(SEEDS)):
                if not ok[j]:
                    v.append(None)
                    continue
                v.append(sum(cells[k][j] * sign(k) for k in CELLS) / 4.0)
            return summ(v)
        sgn = lambda k, i: 1 if k[i] == 'o' else -1   # noqa: E731
        inter = {}
        for (i, j) in ((0, 1), (0, 2), (1, 2)):
            s_ = contrast(lambda k: sgn(k, i) * sgn(k, j))
            inter[f'{FACT[i]} × {FACT[j]}'] = s_
        inter['ba chiều'] = contrast(lambda k: sgn(k, 0) * sgn(k, 1) * sgn(k, 2))
        for nm, s_ in inter.items():
            if s_:
                print(f'    tương tác {nm:34s} {s_["mean"]:+.2f} [{s_["mean"] - s_["ci95"]:+.2f}, '
                      f'{s_["mean"] + s_["ci95"]:+.2f}]')
        tot = [sum(x) if x else None for x in sh]
        if gap and summ(tot):
            print(f'    tổng Shapley {summ(tot)["mean"]:+.2f} = khoảng cách {gap["mean"]:+.2f}')
        po = paired(ing, cells[('r', 'r', 'r')])
        print(f'    chỉ đổi ingest sang chạy hết ngân sách: {fp(po)}')
        pr = paired(cells[('o', 'o', 'o')], ref)
        print(f'    ô toàn oracle − mô hình lý tưởng: {fp(pr)}')
        if pr and not (pr['lo'] <= 0 <= pr['hi']):
            print('      ô toàn oracle KHÔNG trùng mô hình lý tưởng trong KTC: phần chênh là khác biệt giữa '
                  'hai simulator, phải nêu trong bài')
        out[ds] = {'cells': {'/'.join(k): summ(v) for k, v in cells.items()}, 'gap': gap,
                   'main_effects': main_eff, 'shapley': shap, 'interactions': inter,
                   'ingest_full_minus_main': po, 'all_oracle_minus_ideal': pr,
                   'placement_exact': {'main': plm, **pl}, 'near20': {'join': cov_j, 'full': cov_f}}
    SUMMARY['decomposition'] = out


# ------------------------------------------------------------------ 4. control
CTL = [('ctl_random_unique', 'random equal peers', 'random_unique'),
       ('ctl_random_keys', 'random keyed', 'random_keys'),
       ('ctl_random_slots', 'random nominal', 'random_slots'),
       ('ctl_random_equalcand', 'random candidate threshold', 'random_equalcand')]


def controls(st, st1):
    head('4. CONTROL TRÊN MÔ HÌNH ITERATIVE (cột iterative cho Bảng 4), 10 seed')
    out = {}
    for ds in DS:
        sem = iv(st, 'sem', ds, 'base', R5)
        print(f'  {ds}: {"":28s} {"R@5 iterative":>15s} {"peer %":>7s} {"ứng viên":>9s} | {"R@5 lý tưởng":>14s}')
        print(f'    {"semantic":28s} {fm(summ(sem)):>15s} {fmean(summ(iv(st, "sem", ds, "base", PPCT)), 1):>7s} '
              f'{fmean(summ(iv(st, "sem", ds, "base", CAND)), 0):>9s} | '
              f'{fm(summ(ideal(st1, "t4", f"{ds}_semantic", lambda d: d["recall5"]))):>14s}')
        rows = {}
        for vn, lab, m1 in CTL:
            r5 = iv(st, 'sem', ds, vn, R5)
            p = paired(sem, r5)
            rows[lab] = {'r5': summ(r5), 'diff': p}
            idl = ideal(st1, 't4', f'{ds}_{m1}', lambda d: d['recall5'])
            print(f'    {lab:28s} {fm(summ(r5)):>15s} {fmean(summ(iv(st, "sem", ds, vn, PPCT)), 1):>7s} '
                  f'{fmean(summ(iv(st, "sem", ds, vn, CAND)), 0):>9s} | {fm(summ(idl)):>14s}')
            print(f'      semantic − {lab}: {fp(p)}')
        out[ds] = rows
    SUMMARY['controls'] = out


# ------------------------------------------------------------------ 5. Bucket-LSH
def bucket(st, st1):
    head('5. BUCKET-LSH TRÊN MÔ HÌNH ITERATIVE: T = 8, b chọn trên validation ở đợt 1 (theo từng seed)')
    out = {}
    for ds in DS:
        bs = [JB.B_LSH_T8[ds][i] for i in range(len(SEEDS))]
        lsh = []
        for i, s in enumerate(SEEDS):
            v = var(st, 'lsh', f'{ds}_T8', f'bucket_b{bs[i]}_T8', s)
            lsh.append(v)
        r5 = [None if v is None else v['recall_at_5'] for v in lsh]
        sem = iv(st, 'sem', ds, 'base', R5)
        found = [None if v is None else 100.0 * v['bucket_probes_found'] / max(1, v['lookups_total'])
                 for v in lsh]
        print(f'  {ds}: b theo seed {bs}')
        print(f'    Bucket-LSH iterative: R@5 {fm(summ(r5))} | peer {fmean(summ([v and v["mean_contacted"] for v in lsh]), 0)} '
              f'| RPC {fmean(summ([v and v["mean_rpcs"] for v in lsh]), 0)} | ứng viên '
              f'{fmean(summ([v and v["mean_candidates"] for v in lsh]), 0)} | probe tìm thấy bucket '
              f'{fmean(summ(found), 1)}% | trùng K thật {fmean(summ([v and 100 * v["truek_overlap_mean"] for v in lsh]), 1)}%')
        print(f'    V-Engram iterative:   R@5 {fm(summ(sem))} | peer {fmean(summ(iv(st, "sem", ds, "base", PEER)), 0)} '
              f'| RPC {fmean(summ(iv(st, "sem", ds, "base", RPC)), 0)} | ứng viên '
              f'{fmean(summ(iv(st, "sem", ds, "base", CAND)), 0)}')
        p = paired(sem, r5)
        print(f'    V-Engram − Bucket-LSH (iterative): {fp(p)}')
        print(f'      lồng nhau: {nested(sem, r5)}')
        # Bucket-LSH lý tưởng của đợt 1 ở đúng b của từng seed (test, T = 8)
        il5, ilp = [], []
        for i, s in enumerate(SEEDS):
            d1 = st1.get('lsh', f'{ds}_T8_test', s) if st1 is not None else None
            w = {x['b']: x for x in d1['widths']} if d1 else {}
            il5.append(w[bs[i]]['recall5'] if bs[i] in w else None)
            ilp.append(w[bs[i]]['pool_mean'] if bs[i] in w else None)
        cand = [v and v['mean_candidates'] for v in lsh]
        frac = [c / q for c, q in zip(cand, ilp) if c is not None and q]
        print(f'    Bucket-LSH lý tưởng cùng b (đợt 1): R@5 {fm(summ(il5))} | ứng viên {fmean(summ(ilp), 0)} | '
              f'iterative − lý tưởng {fp(paired(r5, il5))} | iterative thu được '
              f'{100 * mean_of(frac) if frac else float("nan"):.1f}% số ứng viên lý tưởng')
        out[ds] = {'bucket_r5': summ(r5), 'vengram_r5': summ(sem), 'diff': p, 'b': bs,
                   'ideal_same_b': summ(il5), 'iter_minus_ideal': paired(r5, il5)}
    SUMMARY['bucket_lsh_iterative'] = out


# ------------------------------------------------------------------ 6. mất peer
def loss(st, st1):
    head('6. MẤT PEER TRÊN MÔ HÌNH ITERATIVE (code): peer chết sau ingest, không sửa, 10 seed')
    rows = [('r = 1, 0%', ('sem', 'code', 'base'), ('t4', 'code_semantic')),
            ('r = 1, 20%', ('sem', 'code', 'loss0.20'), ('loss', 'code_r1_loss0.20')),
            ('r = 1, 30%', ('sem', 'code', 'loss0.30'), ('loss', 'code_r1_loss0.30')),
            ('r = 2, 0%', ('loss', 'code_r23', 'r2_loss0.00'), ('t8', 'code_r2_semantic')),
            ('r = 2, 30%', ('loss', 'code_r23', 'r2_loss0.30'), ('loss', 'code_r2_loss0.30')),
            ('r = 3, 0%', ('loss', 'code_r23', 'r3_loss0.00'), ('loss', 'code_r3_loss0.00')),
            ('r = 3, 30%', ('loss', 'code_r23', 'r3_loss0.30'), ('loss', 'code_r3_loss0.30'))]
    print(f'    {"":12s} {"R@5 iterative":>15s} {"R@5 lý tưởng":>14s} {"peer":>6s} {"RPC":>6s} '
          f'{"lookup < K":>10s} {"trùng K thật":>12s}')
    out = {}
    for lab, (g, j, vn), (g1, n1) in rows:
        r5 = iv(st, g, j, vn, R5)
        idl = ideal(st1, g1, n1, lambda d: d['recall5'])
        print(f'    {lab:12s} {fm(summ(r5)):>15s} {fm(summ(idl)):>14s} {fmean(summ(iv(st, g, j, vn, PEER)), 0):>6s} '
              f'{fmean(summ(iv(st, g, j, vn, RPC)), 0):>6s} {fmean(summ(iv(st, g, j, vn, SHORT)), 2):>9s}% '
              f'{fmean(summ(iv(st, g, j, vn, TRUEK)), 1):>11s}%')
        out[lab] = {'iter': summ(r5), 'ideal': summ(idl), 'iter_minus_ideal': paired(r5, idl)}
    SUMMARY['loss_iterative'] = out


# ------------------------------------------------------------------ 7. 25.000 peer
def scale(st, st1):
    head('7. 25.000 PEER TRÊN MÔ HÌNH ITERATIVE (code50k, 10 seed), so với mô hình lý tưởng cùng seed')
    out = {}
    for K in (50, 20):
        r5 = iv(st, 'ws', 'code50k_N25000', f'K{K}', R5)
        idl = ideal(st1, 'ws', f'code50k_N25000_K{K}_semantic', lambda d: d['recall5'])
        ratio = [a / b for a, b in zip(r5, idl) if a is not None and b]
        print(f'  K = {K}: iterative {fm(summ(r5))} | lý tưởng {fm(summ(idl))} | iterative − lý tưởng '
              f'{fp(paired(r5, idl))} | tỉ lệ {mean_of(ratio) if ratio else float("nan"):.3f}')
        print(f'    peer {fmean(summ(iv(st, "ws", "code50k_N25000", f"K{K}", PPCT)), 2)}% | RPC '
              f'{fmean(summ(iv(st, "ws", "code50k_N25000", f"K{K}", RPC)), 0)} | lookup < K '
              f'{fmean(summ(iv(st, "ws", "code50k_N25000", f"K{K}", SHORT)), 2)}%')
        out[f'K{K}'] = {'iter': summ(r5), 'ideal': summ(idl), 'diff': paired(r5, idl)}
    r10 = iv(st, 'sem', 'code', 'base', R5)
    i10 = ideal(st1, 't4', 'code_semantic', lambda d: d['recall5'])
    ratio = [a / b for a, b in zip(r10, i10) if a is not None and b]
    print(f'  đối chiếu 10.000 peer, K = 20: iterative − lý tưởng {fp(paired(r10, i10))} | tỉ lệ '
          f'{mean_of(ratio) if ratio else float("nan"):.3f}')
    SUMMARY['scale_25k'] = out


# ------------------------------------------------------------------ 8, 9. cặp c, margin
def cpair_margin(st):
    head('8. CẶP c TRÊN MÔ HÌNH ITERATIVE: (c = 16, T = 8) so với (c = 9, T = 5), 10 seed')
    out = {}
    for ds in DS:
        a, b = iv(st, 'sem', ds, 'base', R5), iv(st, 'sem', ds, 'c9_T5', R5)
        print(f'  {ds}: c16 T8 {fm(summ(a))} | c9 T5 {fm(summ(b))} | khác {fp(paired(b, a))}')
        for lab, f in (('lookup/query', LOOKUPS), ('RPC routing', RRT), ('RPC đánh giá', REV), ('peer', PEER)):
            x, y = summ(iv(st, 'sem', ds, 'base', f)), summ(iv(st, 'sem', ds, 'c9_T5', f))
            red = None if not x or not y else 100 * (1 - y['mean'] / x['mean'])
            print(f'    {lab:13s} {fmean(x, 1):>8s} -> {fmean(y, 1):>8s}' +
                  ('' if red is None else f'  (giảm {red:.1f}%)'))
        out[ds] = {'c16_T8': summ(a), 'c9_T5': summ(b), 'diff': paired(b, a)}
    SUMMARY['c_pair_iterative'] = out
    head('9. MARGIN ABLATION TRÊN MÔ HÌNH ITERATIVE: lật bit theo margin so với lật ngẫu nhiên, 10 seed')
    out = {}
    for ds in DS:
        a, b = iv(st, 'sem', ds, 'base', R5), iv(st, 'sem', ds, 'abl_random_order', R5)
        p = paired(a, b)
        print(f'  {ds}: margin {fm(summ(a))} | ngẫu nhiên {fm(summ(b))} | margin − ngẫu nhiên {fp(p)} | '
              f'peer {fmean(summ(iv(st, "sem", ds, "base", PEER)), 0)} -> '
              f'{fmean(summ(iv(st, "sem", ds, "abl_random_order", PEER)), 0)}')
        out[ds] = {'margin': summ(a), 'random': summ(b), 'diff': p}
    SUMMARY['margin_ablation_iterative'] = out


# ------------------------------------------------------------------ 10. frontier, RPC, vòng
def frontier(st):
    head('10. FRONTIER RỖNG, TÁCH RPC ROUTING VÀ RPC ĐÁNH GIÁ, SỐ VÒNG MỖI LOOKUP (cấu hình chính)')
    out = {}
    for ds in DS:
        cmin = [v and v['overlay_contacts_min'] for v in (var(st, 'sem', ds, 'base', s) for s in SEEDS)]
        cmean = summ(iv(st, 'sem', ds, 'base', lambda v: v['overlay_contacts_mean']))
        short = sum(x for x in iv(st, 'sem', ds, 'base', lambda v: v['short_lookups']) if x)
        nprobe = sum(x for x in iv(st, 'sem', ds, 'base', lambda v: v['probe_lookups']) if x)
        hist = collections.Counter()
        for v in (var(st, 'sem', ds, 'base', s) for s in SEEDS):
            if v:
                hist.update({int(h): c for h, c in v['query_hops_hist'].items()})
        tot = sum(hist.values())
        cum, p50, p90 = 0, None, None
        for h in sorted(hist):
            cum += hist[h]
            if p50 is None and cum >= 0.5 * tot:
                p50 = h
            if p90 is None and cum >= 0.9 * tot:
                p90 = h
        rmax = max(hist) if hist else None
        print(f'  {ds}: contact sau join TB {fmean(cmean, 1)}, nhỏ nhất qua 10 seed '
              f'{min(x for x in cmin if x is not None) if any(x is not None for x in cmin) else "—"}')
        print(f'    lookup truy vấn trả ít hơn K peer: {short}/{nprobe}')
        print(f'    RPC routing {fmean(summ(iv(st, "sem", ds, "base", RRT)), 1)} + RPC đánh giá '
              f'{fmean(summ(iv(st, "sem", ds, "base", REV)), 1)} = {fmean(summ(iv(st, "sem", ds, "base", RPC)), 1)} mỗi query')
        if tot:
            mean_h = sum(h * c for h, c in hist.items()) / tot
            print(f'    số vòng mỗi lookup truy vấn: TB {mean_h:.2f}, trung vị {p50}, P90 {p90}, lớn nhất {rmax}; '
                  f'phân bố {dict(sorted(hist.items()))}')
        for lab, g, j, vn in (('mất 30%, r = 1', 'sem', ds, 'loss0.30'),):
            sh = iv(st, g, j, vn, lambda v: v['short_lookups'])
            npb = iv(st, g, j, vn, lambda v: v['probe_lookups'])
            if any(x is not None for x in sh):
                print(f'    {lab}: lookup trả ít hơn K peer {sum(x for x in sh if x)}/{sum(x for x in npb if x)}')
        out[ds] = {'contacts_min': cmin, 'short': short, 'probes': nprobe, 'hops_hist': dict(hist)}
    SUMMARY['frontier'] = out


# ------------------------------------------------------------------ 11, 12. lý tưởng
def gauss_per_table(st, st1):
    head('11. GAUSSIAN KÈM THỐNG KÊ TỪNG BẢNG CHIẾU (lý tưởng, 10 seed), so với Achlioptas của đợt 1')
    out = {}
    for ds in DS:
        rows = {}
        for lab, src, grp, nm in (('Achlioptas', st1, 't4', f'{ds}_semantic'),
                                  ('Gaussian', st, 'gpt', f'{ds}_gauss_semantic')):
            if src is None:
                continue
            r5 = src.vals(grp, nm, lambda d: d['recall5'])
            spread = src.vals(grp, nm, lambda d: max(d['p_each']) / max(1e-9, min(d['p_each'])))
            pbar = src.vals(grp, nm, lambda d: 100 * d['p_bar'])
            corr = src.vals(grp, nm, lambda d: d['table_pair_corr_mean'])
            short = src.vals(grp, nm, lambda d: 100 * d['or_shortfall'])
            gin = src.vals(grp, nm, lambda d: d['metadata_gini'])
            rows[lab] = {'r5': summ(r5), 'spread': summ(spread), 'p_bar': summ(pbar), 'corr': summ(corr),
                         'gini': summ(gin)}
            print(f'  {ds} {lab:11s} R@5 {fm(summ(r5)):>12s} | p từng bảng TB {fmean(summ(pbar), 1)}% | '
                  f'chênh lớn nhất/nhỏ nhất {fmean(summ(spread), 2)} (max {summ(spread)["max"] if summ(spread) else 0:.2f}) | '
                  f'tương quan cặp bảng {fmean(summ(corr), 3)} | thiếu hụt OR {fmean(summ(short), 1)} điểm | '
                  f'Gini {fmean(summ(gin), 2)}')
        out[ds] = rows
        # hồi quy: cùng seed, cùng cấu hình với nhóm r11 của đợt 1 (chỉ thêm cờ thống kê từng bảng)
        if st1 is not None:
            a = st.vals('gpt', f'{ds}_gauss_semantic', lambda d: d['recall5'])
            b = st1.vals('r11', f'{ds}_gauss_semantic', lambda d: d['recall5'])
            pairs_ = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
            same = sum(1 for x, y in pairs_ if x == y)
            print(f'    hồi quy với r11 của đợt 1: {same}/{len(pairs_)} seed trùng recall')
            if same != len(pairs_):
                problem(f'{ds}: Gaussian của đợt 2 lệch r11 của đợt 1 ở {len(pairs_) - same} seed')
    SUMMARY['gauss_per_table'] = out


JINA = [('cấu hình chính (T 8, K 20, L 5)', ('r14', 'code_jina_semantic'), ('t4', 'code_semantic')),
        ('T = 12', ('jina', 'code_jina_T12_K20'), ('t5', 'code_T12_K20')),
        ('K = 40', ('jina', 'code_jina_T8_K40'), ('t5', 'code_T8_K40')),
        ('K = 80', ('jina', 'code_jina_T8_K80'), ('t5', 'code_T8_K80')),
        ('L = 8', ('jina', 'code_jina_L8'), ('r11', 'code_L8_semantic')),
        ('L = 8, T = 5', ('jina', 'code_jina_L8_T5'), ('r11', 'code_L8_T5_semantic'))]


def jina(st, st1):
    head('12. SWEEP NGÂN SÁCH CHO JINA (lý tưởng, code, 10 seed), so với BGE cùng cấu hình (đợt 1)')
    print(f'    {"":32s} {"jina R@5":>12s} {"peer %":>7s} {"Gini":>5s} | {"BGE R@5":>12s} {"peer %":>7s}')
    out = {}
    for lab, (g, n), (g1, n1) in JINA:
        src = st1 if g == 'r14' else st
        if src is None:
            continue
        r5 = src.vals(g, n, lambda d: d['recall5'])
        pe = src.vals(g, n, lambda d: d['pct_network_touched'])
        gi = src.vals(g, n, lambda d: d['metadata_gini'])
        b5 = ideal(st1, g1, n1, lambda d: d['recall5'])
        bp = ideal(st1, g1, n1, lambda d: d['pct_network_touched'])
        print(f'    {lab:32s} {fm(summ(r5)):>12s} {fmean(summ(pe), 1):>7s} {fmean(summ(gi), 2):>5s} | '
              f'{fm(summ(b5)):>12s} {fmean(summ(bp), 1):>7s}')
        out[lab] = {'jina': summ(r5), 'jina_peers': summ(pe), 'bge': summ(b5), 'bge_peers': summ(bp)}
    SUMMARY['jina_budget'] = out


# ------------------------------------------------------------------ 13. thời gian
def timing(st, smoke_root):
    head('13. THỜI GIAN VÀ BỘ NHỚ')
    by = collections.defaultdict(list)
    rss = collections.defaultdict(list)
    for k, d in st.d.items():
        if isinstance(d, dict) and 'timing' in d:
            g = k.split('/')[0] + '/' + k.split('/')[1].rsplit('_s', 1)[0]
            by[g].append(d['timing'].get('total', 0))
            rss[g].append(d.get('peak_rss_mb', 0))
    for g in sorted(by):
        print(f'  {g:24s} {len(by[g]):3d} job | TB {sum(by[g]) / len(by[g]) / 60:6.1f} phút | '
              f'RSS đỉnh lớn nhất {max(rss[g]):6.0f} MB')
    if smoke_root and os.path.isdir(smoke_root):
        for p in sorted(os.listdir(os.path.join(smoke_root, 'sm'))) if os.path.isdir(os.path.join(smoke_root, 'sm')) else []:
            if p.startswith('probe') and p.endswith('.json'):
                with open(os.path.join(smoke_root, 'sm', p), encoding='utf-8') as fh:
                    d = json.load(fh)
                e = d.get('estimate_full', {})
                print(f'  smoke {p}: N = {d["nodes"]}, join {e.get("join_s", 0) / 60:.1f} phút, ingest ước '
                      f'{e.get("ingest_s", 0) / 60:.1f} phút, mỗi biến thể 500 query ước '
                      f'{e.get("query_s_per_variant_500q", 0) / 60:.1f} phút, RSS đỉnh {d.get("peak_rss_mb", 0):.0f} MB')


# ------------------------------------------------------------------ smoke check
def smoke_check(root):
    jobs = JB.build_smoke()
    bad = 0
    for j in jobs:
        p = j['out'].replace('ppna_r1/logs_dot2/smoke/out', root, 1)
        err = []
        try:
            with open(p, encoding='utf-8') as fh:
                d = json.load(fh)
        except Exception as e:  # noqa: BLE001
            print(f'  LỖI {j["id"]}: không đọc được {p} ({e})')
            bad += 1
            continue
        if j['kind'] == 'iter':
            vs = d.get('variants', {})
            if not vs:
                err.append('không có biến thể nào')
            for n, v in vs.items():
                if v.get('recall_at_5') is None:
                    err.append(f'{n}: thiếu recall')
                for x in ('truek_overlap_mean', 'short_lookups', 'query_hops_hist', 'rules', 'lookup_stats'):
                    if x not in v:
                        err.append(f'{n}: thiếu {x}')
            plan = j['cmd'][j['cmd'].index('--plan') + 1]
            need = {'sem': ['base', 't7_exhaust-all_R30', 'ctl_random_equalcand', 'q_oracle', 'loss0.30'],
                    'dec': ['Po_Tj_Qo', 'Pfull_Tj_Qr', 'Pr_Tf_Qr', 'Po_Tf_Qo'],
                    'lsh': ['bucket_b10_T8'], 'loss': ['r2_loss0.30', 'r3_loss0.30'],
                    'ws': ['K50', 'K20'], 'probe': ['K50' if '25000' in j['id'] else 'K100']}[plan]
            err += [f'thiếu biến thể {x}' for x in need if x not in vs]
            if plan == 'dec' and 'Po_Tj_Qo' in vs and 'Po_Tf_Qo' in vs and \
                    vs['Po_Tj_Qo']['per_query_hits5'] != vs['Po_Tf_Qo']['per_query_hits5']:
                err.append('hai ô toàn oracle khác nhau')
            if plan == 'probe':
                e = d.get('estimate_full', {})
                print(f'  {j["id"]}: join {e.get("join_s", 0) / 60:.1f} phút, ingest ước {e.get("ingest_s", 0) / 60:.1f} '
                      f'phút, 500 query ước {e.get("query_s_per_variant_500q", 0) / 60:.1f} phút, RSS đỉnh '
                      f'{d.get("peak_rss_mb", 0):.0f} MB')
        else:
            need = ['recall5', 'proj_family', 'normalize_cols', 'commit']
            if '--per-table-stats' in j['cmd']:
                need += ['table_pair_corr_mean', 'p_each']
            err += [f'thiếu {x}' for x in need if x not in d]
            if 'jina' in j['id'] and d.get('dim') != 896:
                err.append(f'dim {d.get("dim")} khác 896')
        if err:
            bad += 1
            print(f'  LỖI {j["id"]}: {"; ".join(err[:6])}')
        else:
            print(f'  đạt {j["id"]}')
    print(f'SMOKE CHECK: {len(jobs) - bad}/{len(jobs)} đạt')
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-root', default='ppna_r1/out_dot2')
    ap.add_argument('--dot1-root', default='ppna_r1/out_dot1')
    ap.add_argument('--verify-s2', default='ppna_r1/out_verify_s2')
    ap.add_argument('--smoke-root', default='ppna_r1/logs_dot2/smoke/out')
    ap.add_argument('--summary', default=None)
    ap.add_argument('--smoke-check', default=None, metavar='DIR')
    a = ap.parse_args()
    if a.smoke_check:
        return smoke_check(a.smoke_check)
    st = Store(a.out_root)
    st1 = Store(a.dot1_root) if os.path.isdir(a.dot1_root) else None
    print(f'TỔNG HỢP ĐỢT 2 | {len(st.d)} file kết quả trong {a.out_root} | đợt 1: '
          f'{len(st1.d) if st1 else 0} file trong {a.dot1_root}')
    if st1 is None:
        problem(f'không thấy {a.dot1_root}: các phép so với mô hình lý tưởng bị bỏ')
    completeness(st)
    regression(st, a.verify_s2)
    for fn, args in ((table7, (st,)), (decomposition, (st, st1)), (controls, (st, st1)),
                     (bucket, (st, st1)), (loss, (st, st1)), (scale, (st, st1)), (cpair_margin, (st,)),
                     (frontier, (st,)), (gauss_per_table, (st, st1)), (jina, (st, st1)),
                     (timing, (st, a.smoke_root))):
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
