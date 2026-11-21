"""Tổng hợp đợt 5: Bảng 10 (churn) trên mô hình iterative, ghép cặp theo seed với mô hình lý tưởng (nhóm
churn của đợt 1), kèm các kiểm tra hồi quy và chi phí giao thức.

    python3 ppna_r1/dot5/aggregate.py --out-root ppna_r1/out_dot5 --ideal-root ppna_r1/out_dot1/churn \\
        --static-root ppna_r1/out_dot3/tk_r --summary ppna_r1/dot5_summary.json
    python3 ppna_r1/dot5/aggregate.py --smoke-check ppna_r1/logs_dot5/smoke/out
"""
import argparse
import importlib.util
import json
import math
import os
import statistics as st

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
CONFIGS = [(1, 0), (1, 480), (4, 1320)]
T9 = 2.2621571627409915          # t(0,975; 9)
SUBMITTED = {(1, 0): (57.5, 23.7, 0.79, 0.0), (1, 480): (99.2, 84.6, 5.77, 13.8),
             (4, 1320): (99.8, 85.3, 21.99, 20.0)}     # Bảng 10 bản nộp: min meta, R@5, bản sống, msg


def _load_jobs():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jobs.py')
    spec = importlib.util.spec_from_file_location('dot5_jobs', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(p):
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def label(r, rep):
    return f'r = {r}, ' + ('không sửa' if rep == 0 else f'sửa mỗi {rep} ph')


def stats(d):
    """Các đại lượng của Bảng 10 từ một file kết quả churn (như churn_stats của đợt 1), cộng R@5 trung
    bình và nhỏ nhất qua các lần đo sau warm-up."""
    h = d['history']
    m = [x for x in h if x.get('epoch', 0) > 0] or h
    cfg = d['config']
    end = h[-1]
    out = {'phys_min': min(x['meta_physical'] for x in m),
           'route_min': min(x['meta_routable'] for x in m),
           'r5_end': end['final_r5'],
           'r5_mean': st.mean(x['final_r5'] for x in h),
           'r5_min': min(x['final_r5'] for x in h),
           'footprint': end['footprint'],
           'msg22': end['repair_msgs'] / d['corpus'] * 1320 / cfg['duration'] if cfg['duration'] else 0.0,
           'departures': [x['departures'] for x in h],
           'n_meas': len(h)}
    if 'final_r5_noreplace' in end:
        # iterative: client không thay peer hết giờ (độ nhạy, cùng các lookup)
        out['r5_end_nr'] = end['final_r5_noreplace']
        out['r5_mean_nr'] = st.mean(x['final_r5_noreplace'] for x in h)
        out['route_min_nr'] = min(x['meta_routable_noreplace'] for x in m)
    return out


def ci(d):
    m = st.mean(d)
    h = T9 * st.stdev(d) / math.sqrt(len(d)) if len(d) > 1 else float('nan')
    return {'mean': m, 'lo': m - h, 'hi': m + h, 'pos': sum(1 for x in d if x > 0), 'n': len(d)}


def iter_costs(d):
    """Chi phí giao thức của một lần chạy iterative."""
    h = d['history']
    pre = d.get('pre') or {}
    cfg = d['config']
    s = d['stats']
    hours = (cfg['warmup'] + cfg['duration']) / 60.0
    n = cfg['nodes']
    joins = max(1, d['total_departures'])
    last = h[-1]['cum']
    # chi phí sửa chữa thật trong pha đo: keep-alive + lookup neo lại + STORE, mỗi object mỗi 22 giờ
    rep_total = sum(last.get(k, 0) for k in ('repair_keepalive_rpcs', 'repair_rpcs', 'repair_store_rpcs'))
    return {
        'pre_r5': pre.get('final_r5'), 'pre_rpcs': pre.get('q_rpcs_mean'),
        'q_rpcs': st.mean(x['q_rpcs_mean'] for x in h),
        'q_lookup_timeouts': st.mean(x['q_lookup_timeouts_mean'] for x in h),
        'q_eval_timeouts': st.mean(x['q_eval_timeouts_mean'] for x in h),
        'q_dead_eval': st.mean(x['q_dead_eval_mean'] for x in h),
        'q_contacted': st.mean(x['nodes_touched'] for x in h),
        'route_rpcs': st.mean(x['route_rpcs_mean'] for x in h),
        'stale': st.mean(x['rt_stale_frac'] for x in h), 'stale_max': max(x['rt_stale_frac'] for x in h),
        'stale_near': st.mean(x['rt_stale_near_frac'] for x in h),
        'live_contacts': st.mean(x['rt_live_contacts_mean'] for x in h),
        'near20': st.mean(x['rt_near20_frac'] for x in h),
        'join_rpcs_per_join': (s.get('join_rpcs', 0) + s.get('join_ping_rpcs', 0) +
                               s.get('join_hello_rpcs', 0)) / joins,
        'join_timeout_frac': s.get('join_timeouts', 0) / max(1, s.get('join_rpcs', 0)),
        'refresh_rpcs_node_h': (s.get('refresh_rpcs', 0) + s.get('refresh_ping_rpcs', 0)) / n / hours,
        'ping_rpcs_node_h': s.get('ping_rpcs', 0) / n / hours,
        'maint_rpcs_node_h': (s.get('join_rpcs', 0) + s.get('join_ping_rpcs', 0) + s.get('join_hello_rpcs', 0) +
                              s.get('refresh_rpcs', 0) + s.get('refresh_ping_rpcs', 0) +
                              s.get('ping_rpcs', 0)) / n / hours,
        'repair_rpcs22': rep_total / d['corpus'] * 1320 / cfg['duration'] if cfg['duration'] else 0.0,
        'repair_timeout_frac': s.get('repair_timeouts', 0) / max(1, s.get('repair_rpcs', 0)),
        'reanchored_frac': (d['n_reanchored'] / max(1, d['n_repairs'] * d['corpus'])) if d['n_repairs'] else None,
        'seconds': d['timing'].get('total'), 'rss_mb': d.get('peak_rss_mb'),
    }


def fms(v, nd=1):
    v = [x for x in v if x is not None]
    if not v:
        return '—'
    sd = st.stdev(v) if len(v) > 1 else 0.0
    tag = '' if len(v) == len(SEEDS) else f' [{len(v)}]'
    return f'{st.mean(v):.{nd}f} ± {sd:.{nd}f}{tag}'


def fci(c, nd=1):
    if c is None:
        return '—'
    return f'{c["mean"]:+.{nd}f} [{c["lo"]:+.{nd}f}; {c["hi"]:+.{nd}f}] dương {c["pos"]}/{c["n"]}'


def summarize(root, ideal_root, static_root, ideal_t0_root=None):
    out = {'configs': {}, 'regression': {}}
    missing = []
    for r, rep in CONFIGS:
        key = f'r{r}_rep{rep}'
        it = {s: read(f'{root}/churn_it/{key}_s{s}.json') for s in SEEDS}
        idl = {s: read(f'{ideal_root}/{key}_s{s}.json') for s in SEEDS}
        missing += [f'churn_it/{key}_s{s}' for s, v in it.items() if v is None]
        missing += [f'ideal/{key}_s{s}' for s, v in idl.items() if v is None]
        row = {'label': label(r, rep), 'iter': {}, 'ideal': {}, 'diff': {}, 'costs': {},
               'seeds_iter': [s for s in SEEDS if it[s]], 'dep_match': None}
        si = {s: stats(it[s]) for s in SEEDS if it[s]}
        sd = {s: stats(idl[s]) for s in SEEDS if idl[s]}
        both = [s for s in SEEDS if s in si and s in sd]
        for k in ('phys_min', 'route_min', 'r5_end', 'r5_mean', 'r5_min', 'footprint', 'msg22'):
            row['iter'][k] = [si[s][k] for s in SEEDS if s in si]
            row['ideal'][k] = [sd[s][k] for s in SEEDS if s in sd]
            if len(both) > 1:
                row['diff'][k] = ci([si[s][k] - sd[s][k] for s in both])
        for k in ('r5_end_nr', 'r5_mean_nr', 'route_min_nr'):
            row['iter'][k] = [si[s][k] for s in SEEDS if s in si and k in si[s]]
        nr = [s for s in SEEDS if s in si and 'r5_mean_nr' in si[s]]
        if len(nr) > 1:
            row['diff']['replace_gain'] = ci([si[s]['r5_mean'] - si[s]['r5_mean_nr'] for s in nr])
        # mốc không churn của từng mô hình: iterative đo ngay sau ingest (pre); lý tưởng tính bằng ideal_t0.py
        it0 = {s: it[s]['pre']['final_r5'] for s in SEEDS if it[s] and it[s].get('pre')}
        id0 = {s: d['final_r5'] for s in SEEDS
               for d in [read(f'{ideal_t0_root}/r{r}_s{s}.json') if ideal_t0_root else None] if d}
        row['iter']['r5_t0'] = [it0[s] for s in SEEDS if s in it0]
        row['ideal']['r5_t0'] = [id0[s] for s in SEEDS if s in id0]
        a_ = [s for s in SEEDS if s in it0 and s in si]
        b_ = [s for s in SEEDS if s in id0 and s in sd]
        if len(a_) > 1:
            row['diff']['iter_drop'] = ci([si[s]['r5_mean'] - it0[s] for s in a_])
        if len(b_) > 1:
            row['diff']['ideal_drop'] = ci([sd[s]['r5_mean'] - id0[s] for s in b_])
        c_ = [s for s in SEEDS if s in it0 and s in si and s in id0 and s in sd]
        if len(c_) > 1:
            row['diff']['t0'] = ci([it0[s] - id0[s] for s in c_])
            row['diff']['drop_diff'] = ci([(si[s]['r5_mean'] - it0[s]) - (sd[s]['r5_mean'] - id0[s]) for s in c_])
        # cùng dòng số phiên: số lượt rời mạng ở mọi lần đo phải trùng mô hình lý tưởng
        both = [s for s in SEEDS if s in si and s in sd]
        row['dep_match'] = [s for s in both if si[s]['departures'] == sd[s]['departures']]
        row['dep_checked'] = both
        costs = {s: iter_costs(it[s]) for s in SEEDS if it[s]}
        if costs:
            for k in next(iter(costs.values())):
                row['costs'][k] = [costs[s][k] for s in SEEDS if s in costs and costs[s][k] is not None]
        out['configs'][key] = row
    # hồi quy: lần đo trước warm-up của mỗi job trùng biến thể base của iterative tĩnh, join đầy đủ (200 query đầu)
    reg = []
    for r, rep in CONFIGS:
        key = f'r{r}_rep{rep}'
        if r != 1:
            continue          # r = 4 dựng mạng ingest khác (r = 4): không có số tĩnh tương ứng
        for s in SEEDS:
            d = read(f'{root}/churn_it/{key}_s{s}.json')
            b = read(f'{static_root}/code_s{s}.json') if static_root else None
            if not d or not d.get('pre') or not b:
                continue
            base = b['variants']['base']['per_query_hits5']
            pre = d['pre']['per_query_hits5']
            reg.append({'job': f'{key}_s{s}', 'same': base[:len(pre)] == pre,
                        'pre_r5': d['pre']['final_r5'], 'static_r5_200': 100.0 * sum(base[:len(pre)]) / (5 * len(pre))})
    out['regression'] = reg
    return out, missing


def report(out, missing):
    print('== Bảng 10 trên mô hình iterative (code, N = 10.000, 10 seed) so với mô hình lý tưởng (đợt 1)')
    print('   iterative: join đầy đủ, học bên gửi mọi RPC, ping peer cũ nhất khi bucket đầy, xoá contact '
          'không trả lời, tự tra chính mình mỗi giờ; neo lại và truy vấn bằng Ripple Search')
    names = [('phys_min', 'min meta vật lý (%)', 1), ('route_min', 'min định tuyến được (%)', 1),
             ('r5_end', 'R@5 lần đo cuối', 1), ('r5_mean', 'R@5 TB các lần đo', 1),
             ('r5_min', 'R@5 nhỏ nhất', 1), ('footprint', 'bản sống / object', 2),
             ('msg22', 'msg sửa / object / 22 giờ', 1)]
    for key, row in out['configs'].items():
        r, rep = (int(x) for x in key[1:].split('_rep'))
        sub = SUBMITTED.get((r, rep))
        print(f'\n  {row["label"]}  (iterative {len(row["seeds_iter"])}/10 seed)')
        print(f'    {"":28s} {"lý tưởng":>14s} {"iterative":>14s}   iterative − lý tưởng [KTC 95%]')
        for k, nm, nd in names:
            print(f'    {nm:28s} {fms(row["ideal"][k], nd):>14s} {fms(row["iter"][k], nd):>14s}   '
                  f'{fci(row["diff"].get(k), nd)}')
        if sub:
            print(f'    bản nộp: min meta {sub[0]}, R@5 {sub[1]}, bản sống {sub[2]}, msg {sub[3]}')
        g2 = lambda k, nd=1: fms(row['iter'].get(k, []), nd)   # noqa: E731
        print(f'    iterative, client không thay peer hết giờ: R@5 TB {g2("r5_mean_nr")}, R@5 cuối {g2("r5_end_nr")}, '
              f'min định tuyến được {g2("route_min_nr")}; lợi của việc thay peer (R@5 TB) {fci(row["diff"].get("replace_gain"))}')
        print(f'    R@5 lúc t = 0 (không churn): lý tưởng {fms(row["ideal"].get("r5_t0", []))}, iterative {g2("r5_t0")}, '
              f'iterative − lý tưởng {fci(row["diff"].get("t0"))}')
        print(f'    suy giảm do churn (R@5 TB các lần đo − R@5 lúc t = 0): lý tưởng {fci(row["diff"].get("ideal_drop"))}; '
              f'iterative {fci(row["diff"].get("iter_drop"))}; hiệu hai mức suy giảm {fci(row["diff"].get("drop_diff"))}')
        if row['dep_checked']:
            print(f'    cùng lượt rời mạng với lý tưởng ở mọi lần đo: {len(row["dep_match"])}/{len(row["dep_checked"])} seed')
        c = row['costs']
        if c:
            g = lambda k, nd=1: fms(c.get(k, []), nd)   # noqa: E731
            print(f'    truy vấn: RPC/query {g("q_rpcs", 0)} (t = 0: {g("pre_rpcs", 0)}), trong đó hết giờ khi lookup '
                  f'{g("q_lookup_timeouts", 0)} và khi đánh giá {g("q_eval_timeouts", 0)}; peer liên lạc {g("q_contacted", 0)}')
            print(f'    định tuyến được: RPC/lookup {g("route_rpcs")}; bảng định tuyến: contact chết {g("stale", 3)} '
                  f'(cao nhất {g("stale_max", 3)}), trong 20 contact gần nhất {g("stale_near", 3)}, '
                  f'contact sống/peer {g("live_contacts", 0)}, phủ 20 láng giềng thật {g("near20", 3)}')
            print(f'    bảo trì overlay (RPC/peer/giờ): tổng {g("maint_rpcs_node_h", 0)}; làm mới {g("refresh_rpcs_node_h", 0)}, '
                  f'ping bucket đầy {g("ping_rpcs_node_h", 0)}; RPC/lần join {g("join_rpcs_per_join", 0)} '
                  f'(hết giờ {g("join_timeout_frac", 3)})')
            print(f'    sửa chữa thật (keep-alive + lookup + STORE)/object/22 giờ {g("repair_rpcs22", 0)}; '
                  f'phần object phải neo lại mỗi vòng {g("reanchored_frac", 3)}; RPC lookup neo lại hết giờ {g("repair_timeout_frac", 3)}')
            print(f'    thời gian {g("seconds", 0)} giây/job, RSS đỉnh {g("rss_mb", 0)} MB')
    reg = out['regression']
    if reg:
        same = sum(1 for x in reg if x['same'])
        print(f'\n== Hồi quy: lần đo trước warm-up trùng biến thể base của iterative tĩnh (join đầy đủ), '
              f'200 query đầu: {same}/{len(reg)} job trùng từng query')
        for x in reg:
            if not x['same']:
                print(f'    KHÁC {x["job"]}: R@5 {x["pre_r5"]:.2f} so với {x["static_r5_200"]:.2f}')
    print(f'\nTHIẾU: {len(missing)} file' + (f' (ví dụ {missing[:3]})' if missing else ''))


def _strip(h):
    return [{k: v for k, v in x.items() if k != 'sec'} for x in h]


def smoke_check(root):
    jobs = _load_jobs().build_smoke()
    bad = 0
    for j in jobs:
        p = j['out'].replace('ppna_r1/logs_dot5/smoke/out', root, 1)
        d = read(p)
        err = []
        if d is None:
            err.append(f'không đọc được {p}')
        else:
            h = d.get('history', [])
            if len(h) < 2:
                err.append('ít hơn hai lần đo')
            if not d.get('pre'):
                err.append('thiếu lần đo trước warm-up')
            for x in h:
                for k in ('meta_physical', 'meta_routable', 'final_r5', 'footprint', 'q_rpcs_mean',
                          'final_r5_noreplace', 'q_eval_timeouts_mean'):
                    if x.get(k) is None:
                        err.append(f'thiếu {k}')
                        break
            cfg = d.get('config', {})
            if cfg.get('repair_interval', 0) > 0 and d.get('n_repairs', 0) < 2:
                err.append('sửa chữa chạy ít hơn hai lần')
            if d.get('total_departures', 0) <= 0:
                err.append('không có lượt rời mạng')
        if err:
            bad += 1
            print(f'  LỖI {j["id"]}: {"; ".join(err)}')
        else:
            print(f'  đạt {j["id"]}: R@5 cuối {d["history"][-1]["final_r5"]:.1f}, {d["total_departures"]} lượt rời mạng, '
                  f'{d["timing"].get("total", 0):.0f} giây')
    # chạy tiếp từ checkpoint phải cho đúng kết quả của lần chạy liền một mạch
    a = read(f'{root}/sm/r1_rep120_s1.json')
    b = read(f'{root}/resume_test.json')
    if a is None or b is None:
        bad += 1
        print('  LỖI chạy tiếp: thiếu file resume_test.json hoặc sm/r1_rep120_s1.json')
    elif b.get('n_resumed', 0) < 1:
        bad += 1
        print('  LỖI chạy tiếp: job kiểm thử không dừng giữa chừng')
    elif _strip(a['history']) != _strip(b['history']) or a['stats'] != b['stats'] or \
            _strip([a['pre']]) != _strip([b['pre']]):
        bad += 1
        print('  LỖI chạy tiếp: kết quả khác lần chạy liền một mạch')
    else:
        print(f'  đạt chạy tiếp từ checkpoint: dừng {b["n_resumed"]} lần, kết quả trùng lần chạy liền một mạch')
    n = len(jobs) + 1
    print(f'SMOKE CHECK: {n - bad}/{n} đạt')
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-root', default='ppna_r1/out_dot5')
    ap.add_argument('--ideal-root', default='ppna_r1/out_dot1/churn')
    ap.add_argument('--static-root', default='ppna_r1/out_dot3/tk_r')
    ap.add_argument('--ideal-t0-root', default='ppna_r1/out_dot5/ideal_t0',
                    help='R@5 lúc t = 0 của mô hình lý tưởng (ppna_r1/dot5/ideal_t0.py)')
    ap.add_argument('--summary', default=None)
    ap.add_argument('--smoke-check', default=None, metavar='DIR')
    a = ap.parse_args()
    if a.smoke_check:
        raise SystemExit(smoke_check(a.smoke_check))
    out, missing = summarize(a.out_root, a.ideal_root, a.static_root, a.ideal_t0_root)
    if a.summary:
        with open(a.summary, 'w', encoding='utf-8') as fh:
            json.dump({'summary': out, 'missing': missing}, fh, indent=1, ensure_ascii=False)
    report(out, missing)


if __name__ == '__main__':
    main()
