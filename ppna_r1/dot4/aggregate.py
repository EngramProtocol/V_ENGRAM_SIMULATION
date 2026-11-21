"""Tổng hợp đợt 4: L = 8 bảng trên mô hình iterative (join đầy đủ và join cũ) so với mô hình lý
tưởng cùng seed, cho mục chọn điểm vận hành (R2-2).

    python3 ppna_r1/dot4/aggregate.py --out-root ppna_r1/out_dot4 --summary ppna_r1/dot4_summary.json
    python3 ppna_r1/dot4/aggregate.py --smoke-check ppna_r1/logs_dot4/smoke/out
"""
import argparse
import importlib.util
import json
import math
import os
import statistics as st

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
T9 = 2.2621571627409915
ROWS = [('L8_T8', 'L8', 'L = 8, T = 8'), ('L8_T5', 'L8_T5', 'L = 8, T = 5 (cùng 40 target)')]
JOINS = [('lt', 'join đầy đủ'), ('lt_old', 'join cũ')]


def _load_jobs():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jobs.py')
    spec = importlib.util.spec_from_file_location('dot4_jobs', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ci(d):
    m = st.mean(d)
    h = T9 * st.stdev(d) / math.sqrt(len(d)) if len(d) > 1 else float('nan')
    return m, m - h, m + h, sum(1 for x in d if x > 0)


def read(p):
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def summarize(root):
    out = {}
    missing = []
    for ds in ('code', 'scifact'):
        for var, lab, title in ROWS:
            ideal = {s: read(f'{root}/r11_L8/{ds}_{lab}_semantic_s{s}.json') for s in SEEDS}
            row = {'title': title, 'ideal': None, 'iter': {}}
            if all(ideal.values()):
                r = [ideal[s]['recall5'] for s in SEEDS]
                row['ideal'] = {'recall_mean': st.mean(r), 'recall_sd': st.stdev(r), 'recall': r,
                                'peers_pct': st.mean(ideal[s]['pct_network_touched'] for s in SEEDS)}
            else:
                missing += [f'r11_L8/{ds}_{lab}_s{s}' for s, v in ideal.items() if not v]
            for grp, jname in JOINS:
                it = {s: read(f'{root}/{grp}/{ds}_s{s}.json') for s in SEEDS}
                if not all(it.values()):
                    missing += [f'{grp}/{ds}_s{s}' for s, v in it.items() if not v]
                    continue
                xs = [it[s]['variants'][var] for s in SEEDS]
                r = [x['recall_at_5'] for x in xs]
                e = {'join': jname, 'recall_mean': st.mean(r), 'recall_sd': st.stdev(r), 'recall': r,
                     'peers_pct': st.mean(x['pct_contacted'] for x in xs),
                     'rpc_mean': st.mean(x['mean_rpcs'] for x in xs),
                     'rpc_routing_mean': st.mean(x['rpc_routing_mean'] for x in xs),
                     'rpc_eval_mean': st.mean(x['rpc_eval_mean'] for x in xs),
                     'rounds_mean': st.mean(x['mean_rounds'] for x in xs)}
                if row['ideal']:
                    e['minus_ideal'] = list(ci([a - b for a, b in zip(r, row['ideal']['recall'])]))
                row['iter'][grp] = e
            out[f'{ds}/{var}'] = row
    return out, missing


def report(out, missing):
    for ds in ('code', 'scifact'):
        print(f'== {ds} (N = 10.000, K = 20, 10 seed, query test)')
        for var, _lab, title in ROWS:
            row = out.get(f'{ds}/{var}')
            if not row:
                continue
            print(f'  {title}')
            if row['ideal']:
                i = row['ideal']
                print(f'    lý tưởng      R@5 {i["recall_mean"]:5.1f} ± {i["recall_sd"]:3.1f} | peer {i["peers_pct"]:4.2f}%')
            for grp, _j in JOINS:
                e = row['iter'].get(grp)
                if not e:
                    continue
                d = e.get('minus_ideal')
                ds_ = f' | − lý tưởng {d[0]:+.2f} [{d[1]:+.2f}; {d[2]:+.2f}] dương {d[3]}/10' if d else ''
                print(f'    {e["join"]:13s} R@5 {e["recall_mean"]:5.1f} ± {e["recall_sd"]:3.1f} | peer {e["peers_pct"]:4.2f}% '
                      f'| RPC {e["rpc_mean"]:5.0f} ({e["rpc_routing_mean"]:.0f} + {e["rpc_eval_mean"]:.0f}){ds_}')
    print(f'THIẾU: {len(missing)} file' + (f' (ví dụ {missing[:3]})' if missing else ''))


def smoke_check(root):
    jobs = _load_jobs().build_smoke()
    bad = 0
    for j in jobs:
        p = j['out'].replace('ppna_r1/logs_dot4/smoke/out', root, 1)
        d = read(p)
        err = []
        if d is None:
            err.append(f'không đọc được {p}')
        elif j['kind'] == 'iter':
            vs = d.get('variants', {})
            err += [f'thiếu biến thể {x}' for x in ('L8_T8', 'L8_T5') if x not in vs]
            err += [f'{n}: thiếu recall' for n, v in vs.items() if v.get('recall_at_5') is None]
            if d.get('env', {}).get('NUM_TABLES') != '8':
                err.append('NUM_TABLES khác 8')
            if vs.get('L8_T5', {}).get('multi_probe') not in (5, None):
                err.append('T của L8_T5 khác 5')
            if '--join-refresh' in j['cmd'] and '1' not in d.get('join_refresh', {}):
                err.append('thiếu thống kê join đầy đủ')
        else:
            if d.get('num_tables') != 8 or d.get('recall5') is None:
                err.append('job lý tưởng thiếu recall hoặc L khác 8')
        if err:
            bad += 1
            print(f'  LỖI {j["id"]}: {"; ".join(err)}')
        else:
            print(f'  đạt {j["id"]}')
    print(f'SMOKE CHECK: {len(jobs) - bad}/{len(jobs)} đạt')
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-root', default='ppna_r1/out_dot4')
    ap.add_argument('--summary', default=None)
    ap.add_argument('--smoke-check', default=None, metavar='DIR')
    a = ap.parse_args()
    if a.smoke_check:
        raise SystemExit(smoke_check(a.smoke_check))
    out, missing = summarize(a.out_root)
    if a.summary:
        with open(a.summary, 'w', encoding='utf-8') as fh:
            json.dump({'rows': out, 'missing': missing}, fh, indent=1, ensure_ascii=False)
    report(out, missing)


if __name__ == '__main__':
    main()
