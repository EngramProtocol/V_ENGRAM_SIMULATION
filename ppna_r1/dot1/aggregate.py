"""Tổng hợp đợt 1: bảng sinh lại, thí nghiệm mới, hồi quy và bảng thay đổi số liệu.

    python3 ppna_r1/dot1/aggregate.py --out-root ppna_r1/out_dot1 \
        --summary ppna_r1/dot1_summary.json > ppna_r1/dot1_report.txt
    python3 ppna_r1/dot1/aggregate.py --smoke-check ppna_r1/logs_dot1/smoke/out

Quy ước: mean ± SD qua seed; KTC 95% theo phân phối t; phép so ghép cặp theo seed.
Ô thiếu seed in kèm [n/10] và được tính là một vấn đề. Mọi kết quả phải đến từ
cùng một commit (đọc từ file .ok); khác commit cũng là một vấn đề.
Dòng cuối: "KẾT LUẬN: k vấn đề".
"""
import argparse
import collections
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jobs as JB  # noqa: E402
import submitted as SUB  # noqa: E402

SEEDS = JB.SEEDS
NESTS = ((5, SEEDS[:5]), (7, SEEDS[:7]), (10, SEEDS))
PROBLEMS = []
CHANGES = []
SUMMARY = collections.OrderedDict()


# ------------------------------------------------------------------ thống kê
def _betacf(a, b, x):
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-14:
            break
    return h


def _betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_p2(t, df):
    """p hai phía của Student t."""
    return _betai(df / 2.0, 0.5, df / (df + t * t))


_TC = {}


def t_crit(df):
    if df not in _TC:
        lo, hi = 0.0, 200.0
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if t_p2(mid, df) > 0.05 else (lo, mid)
        _TC[df] = (lo + hi) / 2
    return _TC[df]


def summ(vals):
    v = [x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))]
    n = len(v)
    if n == 0:
        return None
    m = sum(v) / n
    sd = statistics.stdev(v) if n > 1 else 0.0
    return {'n': n, 'mean': m, 'sd': sd,
            'ci95': t_crit(n - 1) * sd / math.sqrt(n) if n > 1 else float('nan'),
            'min': min(v), 'max': max(v)}


def paired(a, b):
    d = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    n = len(d)
    if n < 2:
        return None
    m = sum(d) / n
    sd = statistics.stdev(d)
    se = sd / math.sqrt(n)
    t = m / se if se > 0 else float('inf')
    hw = t_crit(n - 1) * se
    return {'n': n, 'mean': m, 'lo': m - hw, 'hi': m + hw, 't': t,
            'p': t_p2(abs(t), n - 1) if se > 0 else 0.0, 'pos': sum(1 for x in d if x > 0)}


def fm(s, nd=1):
    if s is None:
        return '—'
    tag = '' if s['n'] == len(SEEDS) else f' [{s["n"]}/10]'
    return f'{s["mean"]:.{nd}f} ± {s["sd"]:.{nd}f}{tag}'


def fmean(s, nd=1):
    if s is None:
        return '—'
    tag = '' if s['n'] == len(SEEDS) else f'[{s["n"]}]'
    return f'{s["mean"]:.{nd}f}{tag}'


def fp(p):
    if p is None:
        return '—'
    return (f'{p["mean"]:+.2f} [{p["lo"]:+.2f}, {p["hi"]:+.2f}] t({p["n"] - 1})={p["t"]:.1f} '
            f'p={p["p"]:.1e} dương {p["pos"]}/{p["n"]}')


def chg(table, row, col, old, new_s, nd=1, key='mean'):
    new = None if new_s is None else (new_s[key] if isinstance(new_s, dict) else new_s)
    CHANGES.append((table, row, col, old, new, nd))


def head(title):
    print()
    print('=' * 100)
    print(title)
    print('=' * 100)


def problem(msg):
    PROBLEMS.append(msg)
    print(f'  *** VẤN ĐỀ: {msg}')


# ------------------------------------------------------------------ dữ liệu
class Store:
    def __init__(self, root):
        self.root = root
        self.d, self.commit, self.incomplete = {}, {}, []
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if not f.endswith('.json'):
                    continue
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, root)[:-5].replace(os.sep, '/')
                if not os.path.isfile(p + '.ok'):
                    self.incomplete.append(rel)
                    continue
                try:
                    with open(p, encoding='utf-8') as fh:
                        self.d[rel] = json.load(fh)
                    with open(p + '.ok') as fh:
                        self.commit[rel] = fh.read().strip()
                except Exception as e:  # noqa: BLE001
                    self.incomplete.append(f'{rel} ({e})')

    def get(self, group, name, seed=None):
        return self.d.get(f'{group}/{name}' if seed is None else f'{group}/{name}_s{seed}')

    def vals(self, group, name, f, seeds=SEEDS):
        out = []
        for s in seeds:
            d = self.get(group, name, s)
            try:
                out.append(None if d is None else f(d))
            except (KeyError, TypeError, ZeroDivisionError, ValueError):
                out.append(None)
        return out


R5 = lambda d: d['recall5']                                       # noqa: E731
REACH = lambda d: d['reachable_recall5']                          # noqa: E731
PEERS = lambda d: d['pct_network_touched']                        # noqa: E731
NPEERS = lambda d: d['mean_nodes_touched']                        # noqa: E731
CAND = lambda d: 100.0 * d['mean_unique_candidates'] / d['n_docs']  # noqa: E731
NCAND = lambda d: d['mean_unique_candidates']                     # noqa: E731


def ref(group_name):
    """Tên ngắn -> (nhóm, tên) của file kết quả; cấu hình chính nằm trong t4."""
    return group_name.split('/', 1)


def series(st, gn, f):
    g, n = ref(gn)
    return st.vals(g, n, f)


def S(st, gn, f):
    return summ(series(st, gn, f))


def nested_line(st, gn, f, nd=1):
    v = series(st, gn, f)
    parts = []
    for n, ss in NESTS:
        sub = [v[SEEDS.index(s)] for s in ss]
        if any(x is None for x in sub):
            parts.append(f'{n} seed: —')
            continue
        s_ = summ(sub)
        parts.append(f'{n} seed: {s_["mean"]:.{nd}f} ± {s_["ci95"]:.{nd}f}')
    return ' | '.join(parts)


def nested_paired(a, b, nd=2):
    parts = []
    for n, ss in NESTS:
        idx = [SEEDS.index(s) for s in ss]
        p = paired([a[i] for i in idx], [b[i] for i in idx])
        parts.append(f'{n} seed: —' if p is None or p['n'] < n
                     else f'{n} seed: {p["mean"]:+.{nd}f} [{p["lo"]:+.{nd}f}, {p["hi"]:+.{nd}f}]')
    return ' | '.join(parts)


# ------------------------------------------------------------------ 0. đầy đủ, phiên bản
def completeness(st):
    head('0. ĐẦY ĐỦ VÀ PHIÊN BẢN')
    expected = JB.build()
    by_g = collections.OrderedDict()
    for j in expected:
        by_g.setdefault(j['group'], []).append(j)
    commits = collections.Counter(st.commit.values())
    print(f'  commit trong file .ok: {dict(commits)}')
    if len(commits) > 1:
        problem(f'kết quả đến từ {len(commits)} commit khác nhau: {dict(commits)}')
    bad_commit = [k for k, d in st.d.items()
                  if isinstance(d, dict) and d.get('commit') and d['commit'] != st.commit.get(k)]
    if bad_commit:
        problem(f'{len(bad_commit)} file có trường commit khác file .ok, ví dụ {bad_commit[:3]}')
    if st.incomplete:
        print(f'  {len(st.incomplete)} file chưa xong (thiếu .ok), ví dụ {st.incomplete[:3]}')
    for g, js in by_g.items():
        miss = [j['id'] for j in js if j['id'] not in st.d]
        print(f'  {g:7s} {len(js) - len(miss):5d}/{len(js):<5d} {JB.GROUPS.get(g, "")}')
        if miss:
            problem(f'nhóm {g} thiếu {len(miss)} kết quả, ví dụ {miss[:4]}')
    # cấu hình chung của mô phỏng lý tưởng
    v2 = [d for k, d in st.d.items() if isinstance(d, dict) and 'recall5' in d and 'key_bits' in d]
    nonorm = sum(1 for d in v2 if not d.get('normalize_cols'))
    zero = sum(d.get('zero_columns_redrawn', 0) for d in v2)
    nq = collections.Counter(d.get('n_query') for d in v2)
    print(f'  mô hình lý tưởng: {len(v2)} file | chuẩn hoá cột: {len(v2) - nonorm}/{len(v2)} | '
          f'cột chiếu toàn 0 phải sinh lại: {zero} | số query: {dict(nq)}')
    if nonorm:
        problem(f'{nonorm} file mô hình lý tưởng không chuẩn hoá cột')
    SUMMARY['zero_columns_redrawn_total'] = zero


# ------------------------------------------------------------------ 1. hồi quy
def _walk_find(root, names):
    found = {}
    skip = {'data', '.git', 'ppna_r1', 'venv', 'venv_prep', '__pycache__', 'node_modules'}
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in skip and not x.startswith('venv')]
        for f in fn:
            if f in names and f not in found:
                found[f] = os.path.join(dp, f)
    return found


def regression(st, verify_norm, verify_s2, old_root):
    head('1. HỒI QUY: code mới phải cho đúng từng số của các lần chạy trước ở cùng cấu hình')
    keys = ['recall5', 'reachable_recall5', 'returned_recall5', 'mean_unique_candidates',
            'mean_nodes_touched', 'metadata_gini', 'rpc_gini', 'work_gini']
    same = near = diff = na = 0
    for ds in ('code', 'scifact'):
        for s in SEEDS:
            new = st.get('t4', f'{ds}_semantic', s)
            p = os.path.join(verify_norm, f'{ds}_T8_norm1_s{s}.json')
            if new is None or not os.path.isfile(p):
                na += 1
                continue
            with open(p) as fh:
                old = json.load(fh)
            rel = {k: abs(old[k] - new[k]) / max(1.0, abs(old[k])) for k in keys if k in old and k in new}
            bad = [k for k, v in rel.items() if v > 1e-12]
            if not bad:
                same += 1
            elif max(rel.values()) <= 1e-5 and not any(k.startswith('recall') or k.endswith('recall5')
                                                       for k in bad):
                # sai khác làm tròn khi cộng số thực (máy hoặc bản numpy khác): không đổi recall
                near += 1
                print(f'  sai khác làm tròn {ds} s{s}: ' + ', '.join(f'{k} {old[k]} -> {new[k]}' for k in bad))
            else:
                diff += 1
                print(f'  LỆCH {ds} s{s}: ' + ', '.join(f'{k} {old[k]:.4f} -> {new[k]:.4f}' for k in bad))
    print(f'  (a) Bảng 4 semantic so với out_verify_norm (norm1): {same} trùng từng số, {near} chỉ khác '
          f'ở mức làm tròn (recall trùng), {diff} lệch, {na} không có file để so')
    if diff:
        problem(f'{diff} lần chạy cấu hình chính lệch với đợt kiểm chuẩn hoá')
    if same + near == 0:
        print('      (không so được: thiếu ppna_r1/out_verify_norm)')
    same = diff = na = 0
    for r in (1, 2, 3):
        new = st.get('regress', f'avail_kbucket_r{r}', SEEDS[0])
        p = os.path.join(verify_s2, 'D', f'kbucket_r{r}_s{SEEDS[0]}.json')
        if new is None or not os.path.isfile(p):
            na += 1
            continue
        with open(p) as fh:
            old = json.load(fh)
        bad = []
        for ro in old['rows']:
            rn = next((x for x in new['rows'] if abs(x['loss'] - ro['loss']) < 1e-9), None)
            for k in ('metadata', 'payload', 'e2e'):
                if rn is None or abs(rn[k] - ro[k]) > 1e-9:
                    bad.append(f'loss {ro["loss"]:.2f} {k}')
        if bad:
            diff += 1
            print(f'  LỆCH availability r={r}: {bad[:4]}')
        else:
            same += 1
    print(f'  (b) availability seed {SEEDS[0]} so với out_verify_s2/D: {same} trùng, {diff} lệch, '
          f'{na} không có file để so')
    if diff:
        problem(f'{diff} lần chạy availability lệch với đợt kiểm 17/11')
    # (c) churn: ba seed cũ
    names = {}
    for r, rep in JB.CHURN_CONFIGS:
        for s in SEEDS[:3]:
            names[f'churn_code_N10000_r{r}_ses120_weibull_rep{rep}{"l" if rep else ""}_s{s}_nq200.json'] = (r, rep, s)
    found = _walk_find(old_root, set(names)) if old_root else {}
    same = diff = 0
    for fname, (r, rep, s) in names.items():
        new = st.get('churn', f'r{r}_rep{rep}', s)
        if fname not in found or new is None:
            continue
        with open(found[fname]) as fh:
            old = json.load(fh)
        ho, hn = old.get('history', []), new.get('history', [])
        bad = len(ho) != len(hn)
        if not bad:
            for a, b in zip(ho, hn):
                for k, v in a.items():
                    if isinstance(v, (int, float)) and k in b and abs(v - b[k]) > 1e-9:
                        bad = True
                        break
        cfg_diff = {k: (old['config'].get(k), new['config'].get(k)) for k in
                    ('duration', 'warmup', 'epoch', 'ttl', 'measure_every', 'repair_mode')
                    if old['config'].get(k) != new['config'].get(k)}
        if bad or cfg_diff:
            diff += 1
            print(f'  KHÁC churn r={r} rep={rep} s={s}: lịch sử {"lệch" if bad else "trùng"}, '
                  f'cấu hình khác: {cfg_diff}')
        else:
            same += 1
    print(f'  (c) churn ba seed cũ so với file của bản đã nộp: {same} trùng, {diff} khác, '
          f'tìm thấy {len(found)}/{len(names)} file cũ')
    SUMMARY['regression_churn_old_found'] = len(found)
    if diff:
        print('      Khác ở đây không phải lỗi code: ghi rõ trong thư trả lời nếu số Bảng 10 đổi.')


# ------------------------------------------------------------------ 2. Bảng 4
def table4(st):
    head('2. BẢNG 4: semantic và bốn control (mô hình lý tưởng, 10 seed)')
    out = {}
    for ds in ('code', 'scifact'):
        print(f'  {ds}')
        print(f'    {"":30s} {"R@5 mới":>16s} {"Peers":>6s} {"Cand.":>6s} | {"R@5 cũ":>11s} '
              f'{"Peers":>5s} {"Cand.":>5s} | {"chênh R@5":>9s}')
        base = series(st, f't4/{ds}_semantic', R5)
        for m in JB.MODES:
            gn = f't4/{ds}_{m}'
            r5, pe, ca = S(st, gn, R5), S(st, gn, PEERS), S(st, gn, CAND)
            o = SUB.T4[ds][m]
            dlt = '—' if r5 is None else f'{r5["mean"] - o[0]:+.1f}'
            print(f'    {SUB.MODE_LABEL[m]:30s} {fm(r5):>16s} {fmean(pe):>6s} {fmean(ca):>6s} | '
                  f'{o[0]:5.1f} ± {o[1]:3.1f} {o[2]:5.1f} {o[3]:5.1f} | {dlt:>9s}')
            chg('Bảng 4', f'{ds}, {SUB.MODE_LABEL[m]}', 'R@5', o[0], r5)
            chg('Bảng 4', f'{ds}, {SUB.MODE_LABEL[m]}', 'SD', o[1], r5, key='sd')
            chg('Bảng 4', f'{ds}, {SUB.MODE_LABEL[m]}', 'Peers %', o[2], pe)
            chg('Bảng 4', f'{ds}, {SUB.MODE_LABEL[m]}', 'Cand. %', o[3], ca)
            out[f'{ds}/{m}'] = {'r5': r5, 'peers': pe, 'cand': ca}
        for m in JB.MODES[1:]:
            print(f'    semantic - {SUB.MODE_LABEL[m]:28s}: {fp(paired(base, series(st, f"t4/{ds}_{m}", R5)))}')
        print(f'    semantic R@5 lồng nhau: {nested_line(st, f"t4/{ds}_semantic", R5)}')
    SUMMARY['table4'] = out


def per_table(st):
    head('3. THỐNG KÊ TỪNG BẢNG CHIẾU (hàng semantic của Bảng 4, --per-table-stats)')
    for ds in ('code', 'scifact'):
        gn = f't4/{ds}_semantic'
        corr = S(st, gn, lambda d: d['table_pair_corr_mean'])
        spread = series(st, gn, lambda d: max(d['p_each']) / max(1e-9, min(d['p_each'])))
        obs = S(st, gn, lambda d: 100 * d['or_observed'])
        ind = S(st, gn, lambda d: 100 * d['or_if_independent'])
        sp = summ(spread)
        print(f'  {ds}: tương quan cặp bảng TB {fm(corr, 3)} (bài: {SUB.TEXT["table_pair_corr"]}) | '
              f'max/min reachability từng bảng: TB {fmean(sp, 2)}, lớn nhất '
              f'{sp["max"] if sp else float("nan"):.2f} | OR đo {fmean(obs)} so với độc lập {fmean(ind)}')
        if ds == 'code':
            chg('Mục 4.3', 'tương quan cặp bảng', 'TB', SUB.TEXT['table_pair_corr'], corr, nd=3)


# ------------------------------------------------------------------ 4. Bảng 5
T5_ROWS = [((1, 20), 't5/code_T1_K20'), ((3, 20), 't5/code_T3_K20'), ((5, 20), 't5/code_T5_K20'),
           ((8, 20), 't4/code_semantic'), ((12, 20), 't5/code_T12_K20'),
           ((8, 10), 't5/code_T8_K10'), ((8, 40), 't5/code_T8_K40'), ((8, 80), 't5/code_T8_K80')]


def table5(st):
    head('4. BẢNG 5: T và K (CodeSearchNet, 10 seed)')
    print(f'    {"":12s} {"Reach":>7s} {"Final mới":>16s} {"Peers":>6s} {"Cand.":>6s} | '
          f'{"Reach":>5s} {"Final":>5s} {"Peers":>5s} {"Cand.":>5s} cũ | gap mới')
    gaps = []
    for (T, K), gn in T5_ROWS:
        re_, r5, pe, ca = S(st, gn, REACH), S(st, gn, R5), S(st, gn, PEERS), S(st, gn, CAND)
        o = SUB.T5[(T, K)]
        gap = None if (re_ is None or r5 is None) else re_['mean'] - r5['mean']
        if gap is not None:
            gaps.append(gap)
        print(f'    T={T:<2d} K={K:<3d}   {fmean(re_):>7s} {fm(r5):>16s} {fmean(pe):>6s} {fmean(ca):>6s} | '
              f'{o[0]:5.1f} {o[1]:5.1f} {o[2]:5.1f} {o[3]:5.1f}    | '
              f'{"—" if gap is None else f"{gap:.1f}"}')
        for i, (col, s_) in enumerate((('Reach R@5', re_), ('Final R@5', r5), ('Peers %', pe),
                                        ('Cand. %', ca))):
            chg('Bảng 5', f'T={T}, K={K}', col, o[i], s_)
    if gaps:
        print(f'  Reachable - Final trên Bảng 5: {min(gaps):.1f} đến {max(gaps):.1f} điểm '
              f'(bài: {SUB.TEXT["reach_final_gap"][0]} đến {SUB.TEXT["reach_final_gap"][1]})')
        CHANGES.append(('Mục 4.3', 'khoảng Reachable - Final', 'nhỏ nhất',
                        SUB.TEXT['reach_final_gap'][0], min(gaps), 1))
        CHANGES.append(('Mục 4.3', 'khoảng Reachable - Final', 'lớn nhất',
                        SUB.TEXT['reach_final_gap'][1], max(gaps), 1))


# ------------------------------------------------------------------ 5. Bảng 6
def _pick(widths, target):
    w = {x['b']: x for x in widths}
    return min(sorted(w), key=lambda b: abs(w[b]['pool_mean'] - target))   # hoà: b nhỏ hơn


def table6(st):
    head('5. BẢNG 6: Bucket-LSH (PQ m = 512, chiếu chuẩn hoá cột như V-Engram); '
         'b_LSH chọn trên VALIDATION rồi đánh giá trên test')
    out = {}
    for ds in ('code', 'scifact'):
        vt_r5 = series(st, f't4/{ds}_semantic', R5)
        vt_c = series(st, f't4/{ds}_semantic', NCAND)
        vv_c = series(st, f'val/{ds}_semantic', NCAND)
        o = SUB.T6[ds]
        print(f'  {ds}: V-Engram ứng viên TB test {fmean(summ(vt_c), 0)}, validation {fmean(summ(vv_c), 0)}')
        print(f'    {"":24s} {"b (mode, khoảng)":>17s} {"ứng viên":>9s} {"R@5 mới":>16s} | '
              f'{"b":>3s} {"ứng viên":>8s} {"R@5 cũ":>11s} | {"R@5 nếu chọn trên test":>22s}')
        lsh8 = None
        for T in (1, 4, 8):
            bsel, rec, pool, rec_or = [], [], [], []
            for i, s in enumerate(SEEDS):
                dv = st.get('lsh', f'{ds}_T{T}_val', s)
                dt = st.get('lsh', f'{ds}_T{T}_test', s)
                if dv is None or dt is None or vv_c[i] is None or vt_c[i] is None:
                    bsel.append(None), rec.append(None), pool.append(None), rec_or.append(None)
                    continue
                wt = {x['b']: x for x in dt['widths']}
                b = _pick(dv['widths'], vv_c[i])
                bsel.append(b)
                rec.append(wt[b]['recall5'])
                pool.append(wt[b]['pool_mean'])
                rec_or.append(wt[_pick(dt['widths'], vt_c[i])]['recall5'])
            bb = [x for x in bsel if x is not None]
            mode = collections.Counter(bb).most_common(1)[0][0] if bb else None
            r5 = summ(rec)
            btxt = '—' if not bb else f'{mode} [{min(bb)}, {max(bb)}]'
            print(f'    {"Bucket-LSH T=" + str(T):24s} {btxt:>17s} {fmean(summ(pool), 0):>9s} {fm(r5):>16s} | '
                  f'{o[T][0]:3d} {o[T][1]:8,d} {o[T][2]:5.1f} ± {o[T][3]:3.1f} | {fm(summ(rec_or)):>22s}')
            chg('Bảng 6', f'{ds}, Bucket-LSH T={T}', 'R@5', o[T][2], r5)
            chg('Bảng 6', f'{ds}, Bucket-LSH T={T}', 'Candidates', o[T][1], summ(pool), nd=0)
            CHANGES.append(('Bảng 6', f'{ds}, Bucket-LSH T={T}', 'b_LSH (mode)', o[T][0], mode, 0))
            out[f'{ds}/T{T}'] = {'r5': r5, 'pool': summ(pool), 'b_mode': mode, 'b_sel': bsel,
                                 'r5_if_selected_on_test': summ(rec_or)}
            if T == 8:
                lsh8 = rec
        r5v = summ(vt_r5)
        print(f'    {"V-Engram":24s} {"–":>17s} {fmean(summ(vt_c), 0):>9s} {fm(r5v):>16s} | '
              f'{"–":>3s} {o["vengram"][0]:8,d} {o["vengram"][1]:5.1f} ± {o["vengram"][2]:3.1f}')
        p = paired(vt_r5, lsh8) if lsh8 else None
        print(f'    V-Engram - Bucket-LSH T=8: {fp(p)}')
        if lsh8:
            print(f'      lồng nhau: {nested_paired(vt_r5, lsh8)}')
        chg('Abstract, Mục 4.4', f'{ds}: V-Engram hơn Bucket-LSH T=8', 'điểm', SUB.T6_GAIN[ds], p)
        # đường quét đầy đủ trên test
        print('    đường quét (test, TB 10 seed): b: R@5 / ứng viên')
        for T in (1, 4, 8):
            rows = collections.defaultdict(lambda: ([], []))
            for s in SEEDS:
                dt = st.get('lsh', f'{ds}_T{T}_test', s)
                if dt is None:
                    continue
                for x in dt['widths']:
                    rows[x['b']][0].append(x['recall5'])
                    rows[x['b']][1].append(x['pool_mean'])
            print(f'      T={T}: ' + '  '.join(
                f'{b}: {sum(r) / len(r):.1f}/{sum(c) / len(c):,.0f}' for b, (r, c) in sorted(rows.items())))
    SUMMARY['table6'] = out


# ------------------------------------------------------------------ 6. Bảng 8
def table8(st):
    head('6. BẢNG 8: nhân bản trong khoá r (CodeSearchNet, 10 seed cho cả hai hàng)')
    print(f'    {"r":>3s} {"semantic mới":>16s} {"cũ":>11s} | {"random nominal mới":>18s} {"cũ":>5s}')
    for r in (1, 2, 4, 5, 10):
        gs = 't4/code_semantic' if r == 1 else f't8/code_r{r}_semantic'
        gr = 't4/code_random_slots' if r == 1 else f't8/code_r{r}_random_slots'
        a, b = S(st, gs, R5), S(st, gr, R5)
        os_, orr = SUB.T8_SEM[r], SUB.T8_RND[r]
        print(f'    {r:3d} {fm(a):>16s} {os_[0]:5.1f} ± {os_[1]:3.1f} | {fm(b):>18s} {orr:5.1f}')
        chg('Bảng 8', f'r={r}', 'semantic R@5', os_[0], a)
        chg('Bảng 8', f'r={r}', 'random nominal R@5', orr, b)


# ------------------------------------------------------------------ 7. Bảng 9 và quét mức mất peer
def _payload_bound(f, n=30, k=20):
    return 100.0 * sum(math.comb(n, i) * (1 - f) ** i * f ** (n - i) for i in range(k, n + 1))


def _final_gn(r, f):
    if f == 0:
        return {1: 't4/code_semantic', 2: 't8/code_r2_semantic', 3: 'loss/code_r3_loss0.00'}[r]
    return f'loss/code_r{r}_loss{f:.2f}'


def _avail_row(d, f):
    return next((x for x in d['rows'] if abs(x['loss'] - f) < 1e-9), None)


def table9(st):
    head('7. BẢNG 9: mất peer tĩnh. Final R@5 lý tưởng; availability trên k-bucket (join), '
         'lookup lặp từ origin ngẫu nhiên; cả hai 10 seed')
    print('    Cột: Final R@5 | metadata routable | payload routable | payload còn >= 20 shard sống '
          '| payload lỡ do lookup | cận giải tích payload')
    out = {}
    for (r, f), o in SUB.T9.items():
        fin = S(st, _final_gn(r, f), R5)
        av = {k: summ(st.vals('avail', f'kbucket_r{r}', lambda d, k=k: _avail_row(d, f)[k]))
              for k in ('metadata', 'payload', 'payload_physical', 'payload_lookup_miss')}
        print(f'    r={r} mất {100 * f:3.0f}%: {fm(fin):>16s} | {fmean(av["metadata"]):>6s} | '
              f'{fmean(av["payload"]):>6s} | {fmean(av["payload_physical"]):>6s} | '
              f'{fmean(av["payload_lookup_miss"]):>5s} | {_payload_bound(f):5.1f}   '
              f'(cũ: {o[0]:.1f} ± {o[1]:.1f}, {o[2]:.1f}, {o[3]:.1f})')
        chg('Bảng 9', f'r={r}, mất {100 * f:.0f}%', 'Final R@5', o[0], fin)
        chg('Bảng 9', f'r={r}, mất {100 * f:.0f}%', 'metadata %', o[2], av['metadata'])
        chg('Bảng 9', f'r={r}, mất {100 * f:.0f}%', 'payload %', o[3], av['payload'])
    print('  Quét đầy đủ (hình): mức mất | Final R@5 r=1, r=2 | metadata r=1/2/3 | payload r=1/2/3 '
          '| payload vật lý r=1 | cận')
    for f in [0.0] + JB.LOSS_LEVELS:
        fin = [S(st, _final_gn(r, f), R5) for r in (1, 2)]
        meta = [summ(st.vals('avail', f'kbucket_r{r}', lambda d: _avail_row(d, f)['metadata']))
                for r in (1, 2, 3)]
        pay = [summ(st.vals('avail', f'kbucket_r{r}', lambda d: _avail_row(d, f)['payload']))
               for r in (1, 2, 3)]
        phys = summ(st.vals('avail', 'kbucket_r1', lambda d: _avail_row(d, f)['payload_physical']))
        print(f'    {100 * f:3.0f}% | {fmean(fin[0]):>6s} {fmean(fin[1]):>6s} | '
              + ' '.join(f'{fmean(x):>6s}' for x in meta) + ' | '
              + ' '.join(f'{fmean(x):>6s}' for x in pay) + f' | {fmean(phys):>6s} | {_payload_bound(f):5.1f}')
        out[f'{f:.2f}'] = {'final_r1': fin[0], 'final_r2': fin[1], 'meta': meta, 'payload': pay,
                           'payload_physical_r1': phys, 'bound': _payload_bound(f)}
    SUMMARY['table9_sweep'] = out


# ------------------------------------------------------------------ 8. Bảng 10
def churn_stats(files):
    rows = []
    for d in files:
        if d is None:
            rows.append(None)
            continue
        h = d['history']
        m = [x for x in h if x.get('epoch', 0) > 0] or h
        cfg = d['config']
        end = h[-1]
        rows.append({
            'phys_min': min(x['meta_physical'] for x in m if 'meta_physical' in x),
            'route_min': min(x['meta_routable'] for x in m if 'meta_routable' in x),
            'meta_end': end.get('meta_avail', end.get('meta_physical')),
            'r5_end': end['final_r5'], 'rand_end': end.get('random_r5'),
            'footprint': end['footprint'],
            'msg22': end['repair_msgs'] / d['corpus'] * 1320 / cfg['duration'] if cfg['duration'] else 0.0,
            'ttl_ratio': (cfg['ttl'] / cfg['repair_interval']) if cfg.get('repair_interval') else None,
            'duration': cfg['duration'], 'warmup': cfg.get('warmup'),
        })
    return rows


def table10(st):
    head('8. BẢNG 10: churn (10 seed)')
    print(f'    {"cấu hình":22s} {"min meta vật lý":>16s} {"min routable":>13s} {"R@5 cuối":>16s} '
          f'{"bản sống":>9s} {"msg/obj":>7s} {"TTL/chu kỳ":>10s} | cũ: min meta, R@5, bản sống, msg')
    for (r, rep), o in SUB.T10.items():
        rows = churn_stats([st.get('churn', f'r{r}_rep{rep}', s) for s in SEEDS])
        g = lambda k: summ([x[k] if x else None for x in rows])  # noqa: E731
        ph, ro, r5, fpn, msg = g('phys_min'), g('route_min'), g('r5_end'), g('footprint'), g('msg22')
        ttl = next((x['ttl_ratio'] for x in rows if x and x['ttl_ratio']), None)
        lbl = f'r={r}, ' + ('không sửa' if rep == 0 else f'sửa mỗi {rep} ph')
        print(f'    {lbl:22s} {fm(ph):>16s} {fmean(ro):>13s} {fm(r5):>16s} {fmean(fpn, 2):>9s} '
              f'{fmean(msg):>7s} {"—" if ttl is None else f"{ttl:.2f}":>10s} | '
              f'{o[0]:.1f}, {o[1]:.1f}, {o[2]:.2f}, {o[3]:.1f}')
        if ph is not None:
            print(f'      min meta vật lý: thấp nhất qua seed {ph["min"]:.1f}; '
                  f'min routable thấp nhất qua seed {ro["min"] if ro else float("nan"):.1f}')
        chg('Bảng 10', lbl, 'Min. metadata', o[0], ph)
        chg('Bảng 10', lbl, 'R@5', o[1], r5)
        chg('Bảng 10', lbl, 'Live copies', o[2], fpn, nd=2)
        chg('Bảng 10', lbl, 'Msg./obj.', o[3], msg)
        if ttl is not None and abs(ttl - SUB.T10_TTL_TEXT) > 0.01:
            print(f'      Lưu ý: TTL trong code = {ttl:.2f} chu kỳ sửa, Mục 4.7 viết '
                  f'{SUB.T10_TTL_TEXT}; sửa văn bản theo code.')


# ------------------------------------------------------------------ 9. Bảng 11, hình 4b, Bảng 12
def ws_gn(N, K, m='semantic'):
    if N == 10000 and K == 20:
        return f't4/code_{m}'
    ds = dict((n, d) for d, n in JB.SCALES)[N]
    return f'ws/{ds}_N{N}_K{K}_{m}'


WORK_MM = lambda d: d['work_max'] / d['work_mean']           # noqa: E731
META_MM = lambda d: d['metadata_max'] / d['metadata_mean_per_node']  # noqa: E731
RPC_MM = lambda d: d['rpc_max'] / d['rpc_mean']               # noqa: E731


def table11(st):
    head('9. BẢNG 11 VÀ HÌNH 4: weak scaling (10 seed mọi điểm)')
    Ns = [10000] + [n for _, n in JB.SCALES]
    for title, Kf in (('K cố định = 20', lambda N: 20), ('K = N/500', lambda N: N // 500)):
        print(f'  {title}')
        print(f'    {"N":>6s} {"K":>4s} {"R@5 mới":>16s} {"Peers":>6s} {"Cand.":>6s} {"random R@5":>10s} '
              f'{"Gini quét":>9s} {"max/mean":>8s} | cũ')
        for N in Ns:
            K = Kf(N)
            gn = ws_gn(N, K)
            r5, pe, ca = S(st, gn, R5), S(st, gn, PEERS), S(st, gn, CAND)
            rnd = S(st, ws_gn(N, K, 'random_slots'), R5) if N in (10000, 25000, 50000) else None
            wg, wm = S(st, gn, lambda d: d['work_gini']), S(st, gn, WORK_MM)
            o = SUB.T11.get((N, K))
            otxt = '' if o is None else f'{o[0]:.1f} ± {o[1]:.1f}, {o[2]:.1f}, {o[3]:.1f}'
            print(f'    {N:6d} {K:4d} {fm(r5):>16s} {fmean(pe):>6s} {fmean(ca):>6s} {fmean(rnd):>10s} '
                  f'{fmean(wg, 2):>9s} {fmean(wm, 0):>8s} | {otxt}')
            if o is not None and N != 10000:
                chg('Bảng 11', f'N={N}, K={K}', 'R@5', o[0], r5)
                chg('Bảng 11', f'N={N}, K={K}', 'SD', o[1], r5, key='sd')
                chg('Bảng 11', f'N={N}, K={K}', 'Peers %', o[2], pe)
                chg('Bảng 11', f'N={N}, K={K}', 'Cand. %', o[3], ca)
            if K == N // 500 and N in SUB.FIG4B:
                chg('Hình 4b', f'N={N}', 'Gini tải quét', SUB.FIG4B[N][0], wg, nd=2)
                chg('Hình 4b', f'N={N}', 'max/mean', SUB.FIG4B[N][1], wm, nd=0)
    pred = SUMMARY.get('predictions', {}).get('weak_scaling_K20_recall_interpolation')
    if pred:
        print('  Dự đoán ghi trước (ngoại suy 6,3 điểm mỗi lần N gấp đôi, K = 20): '
              + ', '.join(f'{n}: {v:.1f}' for n, v in pred['predicted_final_r5'].items()))
    head('10. BẢNG 12: tập trung tải theo peer (CodeSearchNet, N = 10.000, 10 seed)')
    gn = 't4/code_semantic'
    for key, lbl, gf, mf in (('records', 'Discovery records', lambda d: d['metadata_gini'], META_MM),
                             ('adc', 'ADC requests', lambda d: d['rpc_gini'], RPC_MM),
                             ('scan', 'Record-scan load', lambda d: d['work_gini'], WORK_MM)):
        g_, m_ = S(st, gn, gf), S(st, gn, mf)
        o = SUB.T12[key]
        print(f'    {lbl:20s} Gini {fm(g_, 2):>14s}  max/mean {fm(m_, 0):>12s} | cũ {o[0]:.2f} ± {o[1]:.2f}, '
              f'{o[2]} ± {o[3]}')
        chg('Bảng 12', lbl, 'Gini', o[0], g_, nd=2)
        chg('Bảng 12', lbl, 'max/mean', o[2], m_, nd=0)


# ------------------------------------------------------------------ 11. kappa
def kappa(st):
    head('11. KAPPA (số ứng viên mỗi peer trả về), 10 seed')
    for ds in ('code', 'scifact'):
        base = series(st, f't4/{ds}_semantic', R5)
        k10 = series(st, f'kappa/{ds}_kappa10', R5)
        line = []
        for kp in (10, 30, 50, 100):
            gn = f't4/{ds}_semantic' if kp == 30 else f'kappa/{ds}_kappa{kp}'
            line.append(f'kappa={kp}: {fm(S(st, gn, R5))}')
        print(f'  {ds}: ' + ' | '.join(line))
        for kp in (50, 100):
            print(f'    kappa={kp} - kappa=10: {fp(paired(series(st, f"kappa/{ds}_kappa{kp}", R5), k10))}')
        print(f'    kappa=30 - kappa=10: {fp(paired(base, k10))}')


# ------------------------------------------------------------------ 12. R1-1
R11 = [('gauss', 'Gaussian (SRP đẳng hướng)'), ('pq_m64', 'PQ m=64'), ('pq_m128', 'PQ m=128'),
       ('pq_m256', 'PQ m=256'), ('pq_nopq', 'không PQ (cosine chính xác)'), ('L3', 'L=3'), ('L4', 'L=4'),
       ('L6', 'L=6'), ('L8', 'L=8'), ('L10', 'L=10'), ('L8_T5', 'L=8, T=5'), ('c8', 'c=8'),
       ('c9', 'c=9'), ('c12', 'c=12'), ('c24', 'c=24'), ('c9_T5', 'c=9, T=5'), ('c12_T6', 'c=12, T=6')]


def r11(st):
    head('12. R1-1: độ nhạy thiết kế (10 seed, mỗi điểm kèm control random equal peers)')
    out = {}
    for ds in ('code', 'scifact'):
        base = series(st, f't4/{ds}_semantic', R5)
        print(f'  {ds}')
        print(f'    {"cấu hình":30s} {"semantic R@5":>16s} {"random":>7s} {"Peers":>6s} {"Cand.":>6s} '
              f'| semantic - cấu hình chính')
        print(f'    {"chính (Achlioptas, m=512, L=5, c=16)":30s} {fm(S(st, f"t4/{ds}_semantic", R5)):>16s} '
              f'{fmean(S(st, f"t4/{ds}_random_unique", R5)):>7s} '
              f'{fmean(S(st, f"t4/{ds}_semantic", PEERS)):>6s} {fmean(S(st, f"t4/{ds}_semantic", CAND)):>6s}')
        for lab, txt in R11:
            gs, gr = f'r11/{ds}_{lab}_semantic', f'r11/{ds}_{lab}_random_unique'
            r5 = S(st, gs, R5)
            p = paired(series(st, gs, R5), base)
            print(f'    {txt:30s} {fm(r5):>16s} {fmean(S(st, gr, R5)):>7s} {fmean(S(st, gs, PEERS)):>6s} '
                  f'{fmean(S(st, gs, CAND)):>6s} | {fp(p)}')
            out[f'{ds}/{lab}'] = {'r5': r5, 'diff_vs_main': p}
    SUMMARY['r11'] = out


def collision(st):
    head('13. R1-1: tỉ lệ trùng bit theo góc, so với 1 - theta/pi (Eq. 4)')
    for ds in ('code', 'scifact'):
        d = st.get('coll', ds)
        if d is None:
            print(f'  {ds}: —')
            continue
        fa = d['families']
        for fam in ('achlioptas', 'gaussian'):
            x = fa[fam]
            print(f'  {ds} {fam:10s}: lệch tuyệt đối TB {x["weighted_mean_abs_dev"]:.4f}, lớn nhất '
                  f'(bin >= 100 cặp) {x["max_abs_dev_bins_n100"]:.4f}; cột toàn 0 sinh lại: '
                  f'{x["zero_columns_redrawn"]}')
        a = {b['lo']: b for b in fa['achlioptas']['bins']}
        g = {b['lo']: b for b in fa['gaussian']['bins']}
        print('    bin góc: n | Achlioptas | Gaussian | 1 - theta/pi')
        for lo in sorted(a):
            if a[lo]['n'] >= 100 and lo in g:
                print(f'      {lo:4.0f}-{lo + d["bin_deg"]:<4.0f}: {a[lo]["n"]:6d} | {a[lo]["agree_mean"]:.4f} | '
                      f'{g[lo]["agree_mean"]:.4f} | {a[lo]["theory"]:.4f}')


# ------------------------------------------------------------------ 14. R1-4
def r14(st):
    head('14. R1-4: workload và embedding khác (10 seed)')
    for lab, ds, pq in JB.WORKLOADS:
        base = series(st, f'r14/{lab}_semantic', R5)
        d0 = next((st.get('r14', f'{lab}_semantic', s) for s in SEEDS if st.get('r14', f'{lab}_semantic', s)), None)
        info = '' if d0 is None else f' ({d0["n_docs"]:,} object, {d0["dim"]} chiều, PQ {pq})'
        print(f'  {lab}{info}')
        for m in JB.MODES:
            gn = f'r14/{lab}_{m}'
            extra = ''
            if m == 'semantic':
                extra = (f' | Gini record {fmean(S(st, gn, lambda d: d["metadata_gini"]), 2)}, '
                         f'Gini quét {fmean(S(st, gn, lambda d: d["work_gini"]), 2)}, '
                         f'max/mean quét {fmean(S(st, gn, WORK_MM), 0)}')
            else:
                extra = f' | semantic - control: {fp(paired(base, series(st, gn, R5)))}'
            print(f'    {SUB.MODE_LABEL[m]:28s} {fm(S(st, gn, R5)):>16s} {fmean(S(st, gn, PEERS)):>6s} '
                  f'{fmean(S(st, gn, CAND)):>6s}{extra}')


# ------------------------------------------------------------------ 15. khoá cụt
def trunc(st):
    head('15. R1-5, R1-7: khoá cụt b bit (b = 63 là sketch đầy đủ), K = 20, 10 seed')
    for ds, N in (('code', 10000), ('code50k', 25000), ('code100k', 50000)):
        hk = math.log2(N / 20)
        print(f'  N = {N} (h_K = {hk:.1f})')
        print(f'    {"b":>3s} {"R@5":>16s} {"Peers":>6s} {"Cand.":>6s} {"Gini rec":>8s} {"max/mean rec":>12s} '
              f'{"Gini quét":>9s} | full - khoá cụt')
        full = ws_gn(N, 20)
        fv = series(st, full, R5)
        for b in (8, 10, 12, 16, 63):
            gn = full if b == 63 else f'trunc/{ds}_N{N}_b{b}'
            p = None if b == 63 else paired(fv, series(st, gn, R5))
            print(f'    {b:3d} {fm(S(st, gn, R5)):>16s} {fmean(S(st, gn, PEERS)):>6s} {fmean(S(st, gn, CAND)):>6s} '
                  f'{fmean(S(st, gn, lambda d: d["metadata_gini"]), 2):>8s} {fmean(S(st, gn, META_MM), 0):>12s} '
                  f'{fmean(S(st, gn, lambda d: d["work_gini"]), 2):>9s} | {"" if p is None else fp(p)}')


# ------------------------------------------------------------------ 16. mô hình chi phí
def _pred_targets(row):
    g, lab = row['group'], row['label']
    if g == 't5':
        T, K = (int(x.split('=')[1]) for x in lab.split())
        return ['t4/code_semantic'] if (T, K) == (8, 20) else [f't5/code_T{T}_K{K}']
    if g == 'r11':
        key = {'L=8 T=5': 'L8_T5', 'c=9 T=5': 'c9_T5', 'c=12 T=6': 'c12_T6'}.get(lab)
        if key is None:
            a = lab.split()[0]
            key = a.replace('=', '')
        return [f'r11/{ds}_{key}_semantic' for ds in ('code', 'scifact')]
    if g == 'ws':
        N, K = (int(x.split('=')[1]) for x in lab.split())
        return [ws_gn(N, K)]
    if g == 'trunc':
        N, b = (int(x.split('=')[1]) for x in lab.split())
        ds = {10000: 'code', 25000: 'code50k', 50000: 'code100k'}[N]
        return [f'trunc/{ds}_N{N}_b{b}']
    if g == 'loss':
        f = float(lab.split('=')[1])
        return [f'loss/code_r1_loss{f:.2f}']
    return []


def coverage(st, pred_path):
    head('16. MÔ HÌNH CHI PHÍ: số peer phân biệt được đánh giá, dự đoán ghi trước so với đo (TB 10 seed)')
    if not os.path.isfile(pred_path):
        print(f'  không có {pred_path}')
        return
    with open(pred_path, encoding='utf-8') as fh:
        P = json.load(fh)
    SUMMARY['predictions'] = P
    print(f'    {"nhóm":6s} {"cấu hình":16s} {"đo":>8s} {"công thức":>9s} {"Monte Carlo":>11s} '
          f'{"lệch CT (% N)":>13s} {"lệch MC (% N)":>13s}')
    worst_cf = worst_mc = 0.0
    n = 0
    for row in P['rows']:
        vals = []
        for gn in _pred_targets(row):
            vals += [x for x in series(st, gn, NPEERS) if x is not None]
        if not vals:
            continue
        m = sum(vals) / len(vals)
        dcf = 100 * (row['closed_form_peers'] - m) / row['N']
        dmc = 100 * (row['monte_carlo_peers'] - m) / row['N']
        worst_cf, worst_mc = max(worst_cf, abs(dcf)), max(worst_mc, abs(dmc))
        n += 1
        print(f'    {row["group"]:6s} {row["label"]:16s} {m:8.1f} {row["closed_form_peers"]:9.1f} '
              f'{row["monte_carlo_peers"]:11.1f} {dcf:+13.2f} {dmc:+13.2f}')
    print(f'  {n} cấu hình; lệch lớn nhất: công thức {worst_cf:.2f}, Monte Carlo {worst_mc:.2f} điểm % của N')
    SUMMARY['coverage_worst'] = {'n': n, 'closed_form': worst_cf, 'monte_carlo': worst_mc}


# ------------------------------------------------------------------ 17. lồng nhau 5/7/10
def nested(st):
    head('17. ƯỚC LƯỢNG THEO SỐ SEED (5, 7, 10; trung bình ± nửa KTC 95%)')
    items = [('Bảng 4 code semantic', 't4/code_semantic'), ('Bảng 4 scifact semantic', 't4/scifact_semantic')]
    items += [(f'Bảng 4 code {SUB.MODE_LABEL[m]}', f't4/code_{m}') for m in JB.MODES[1:]]
    items += [(f'Bảng 9 r={r} mất {int(100 * f)}%', _final_gn(r, f)) for (r, f) in SUB.T9]
    items += [(f'Bảng 11 N={N} K={K}', ws_gn(N, K)) for (N, K) in SUB.T11 if N != 10000]
    for lbl, gn in items:
        print(f'  {lbl:42s} {nested_line(st, gn, R5)}')


# ------------------------------------------------------------------ 18. bảng thay đổi
def changes():
    head('18. BẢNG THAY ĐỔI SỐ LIỆU so với bản đã nộp (cũ -> mới, chênh)')
    for table, row, col, old, new, nd in CHANGES:
        if new is None:
            print(f'  {table:16s} {row:40s} {col:22s} {old!s:>9s} -> —')
            continue
        if isinstance(new, (int, float)) and isinstance(old, (int, float)):
            print(f'  {table:16s} {row:40s} {col:22s} {old:>9.{nd}f} -> {new:9.{nd}f} ({new - old:+.{nd}f})')
        else:
            print(f'  {table:16s} {row:40s} {col:22s} {old!s:>9s} -> {new!s}')
    SUMMARY['changes'] = [{'table': t, 'row': r, 'col': c, 'old': o,
                           'new': n if not isinstance(n, dict) else n.get('mean')}
                          for t, r, c, o, n, _ in CHANGES]


# ------------------------------------------------------------------ smoke check
def smoke_check(root):
    jobs = JB.build_smoke()
    bad = 0
    for j in jobs:
        p = j['out'].replace('ppna_r1/logs_dot1/smoke/out', root, 1)
        err = []
        try:
            with open(p, encoding='utf-8') as fh:
                d = json.load(fh)
        except Exception as e:  # noqa: BLE001
            print(f'  LỖI {j["id"]}: không đọc được {p} ({e})')
            bad += 1
            continue
        k = j['kind']
        if k == 'v2':
            need = ['recall5', 'key_bits', 'query_set', 'proj_family', 'normalize_cols',
                    'zero_columns_redrawn', 'n_docs', 'dim', 'commit', 'probe_bits']
            if '--per-table-stats' in j['cmd']:
                need += ['table_pair_corr_mean', 'p_each']
            err += [f'thiếu {x}' for x in need if x not in d]
            c = j['cmd']
            if '--key-bits' in c and d.get('key_bits') != int(c[c.index('--key-bits') + 1]):
                err.append('key_bits sai')
            if '--query-set' in c and d.get('query_set') != c[c.index('--query-set') + 1]:
                err.append('query_set sai')
            if '--proj-family' in c and d.get('proj_family') != c[c.index('--proj-family') + 1]:
                err.append('proj_family sai')
            if '--num-tables' in c and d.get('num_tables') != int(c[c.index('--num-tables') + 1]):
                err.append('num_tables sai')
            if d.get('normalize_cols') is not True:
                err.append('không chuẩn hoá cột')
            if 'jina' in j['id'] and d.get('dim') != 896:
                err.append(f'dim {d.get("dim")} khác 896')
        elif k == 'lsh':
            err += [f'thiếu {x}' for x in ('widths', 'pq_m', 'query_set', 'commit') if x not in d]
            if d.get('pq_m') != 512:
                err.append(f'pq_m {d.get("pq_m")} khác 512')
            if d.get('query_set') != j['env']['QUERY_SET']:
                err.append('query_set sai')
        elif k == 'avail':
            r0 = (d.get('rows') or [{}])[0]
            err += [f'thiếu {x}' for x in ('payload_physical', 'payload_lookup_miss', 'mean_alive_shards',
                                            'mean_found_shards_when_failed') if x not in r0]
        elif k == 'churn':
            if not d.get('history'):
                err.append('history rỗng')
            if 'commit' not in d:
                err.append('thiếu commit')
        elif k == 'coll':
            if set(d.get('families', {})) != {'achlioptas', 'gaussian'}:
                err.append('thiếu họ phép chiếu')
        if err:
            bad += 1
            print(f'  LỖI {j["id"]}: {"; ".join(err)}')
        else:
            print(f'  đạt {j["id"]}')
    print(f'SMOKE CHECK: {len(jobs) - bad}/{len(jobs)} đạt')
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-root', default='ppna_r1/out_dot1')
    ap.add_argument('--verify-norm', default='ppna_r1/out_verify_norm')
    ap.add_argument('--verify-s2', default='ppna_r1/out_verify_s2')
    ap.add_argument('--old-root', default='.', help='nơi tìm file churn của bản đã nộp')
    ap.add_argument('--predictions', default=os.path.join(HERE, 'predictions_dot1.json'))
    ap.add_argument('--summary', default=None)
    ap.add_argument('--smoke-check', default=None, metavar='DIR')
    a = ap.parse_args()
    if a.smoke_check:
        return smoke_check(a.smoke_check)
    st = Store(a.out_root)
    print(f'TỔNG HỢP ĐỢT 1 | {len(st.d)} file kết quả trong {a.out_root}')
    completeness(st)
    regression(st, a.verify_norm, a.verify_s2, a.old_root)
    coverage_first = {}
    if os.path.isfile(a.predictions):
        with open(a.predictions, encoding='utf-8') as fh:
            coverage_first = json.load(fh)
        SUMMARY['predictions'] = coverage_first
    for fn in (table4, per_table, table5, table6, table8, table9, table10, table11, kappa, r11,
               collision, r14, trunc):
        try:
            fn(st)
        except Exception as e:  # noqa: BLE001
            problem(f'{fn.__name__} lỗi khi tổng hợp: {type(e).__name__}: {e}')
    coverage(st, a.predictions)
    nested(st)
    changes()
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
