"""Tổng hợp so sánh Semord và V-Engram ở N = 1.000 peer (10 seed, query test, Recall@5).

Semord: file JSON của run_semord.py (stage test). V-Engram: file JSON của iterative.py, kế hoạch ws,
join đầy đủ, K = 2 (= N/500), 4, 10; thêm kế hoạch lt (L = 8, biến thể L8_T5, L8_T8) khi --vengram
có nhiều thư mục, cách nhau bởi dấu phẩy, và --ref-var chọn biến thể để ghép cặp. Số message của Semord lấy từ scalar
overlay_runtime_hot_path_messages_mean của artifact (đếm riêng yêu cầu và trả lời), quy ra số
cặp yêu cầu-trả lời (RPC) bằng tổng số yêu cầu tra cứu trên overlay và yêu cầu tìm kiếm gửi tới
peer (overlay_lookup_requests_mean + overlay_search_dispatch_requests_mean), cùng cách đếm RPC của
V-Engram (một RPC là một cặp yêu cầu-trả lời).
"""
import argparse
import glob
import json
import math
import os
import statistics as st

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
NDOCS = {'code': 20000, 'scifact': 5183}
T9 = 2.2621571627409915


def ci(d):
    m = st.mean(d)
    h = T9 * st.stdev(d) / math.sqrt(len(d)) if len(d) > 1 else float('nan')
    return m, m - h, m + h, sum(1 for x in d if x > 0)


def load_semord(root, N):
    rows = {}
    for f in glob.glob(os.path.join(root, f'*_test_N{N}_B*.json')):
        r = json.load(open(f))
        cfg = (r['rapid_hops'], r['extended_centroids'], r['centroid_top_nodes'], r['centroid_fallback_nodes'])
        rows.setdefault((r['dataset'], r['B'], cfg), {})[r['seed']] = r
    return rows


def load_vengram(roots):
    rows = {}
    for root in roots.split(','):
        for f in glob.glob(os.path.join(root, '*_s*.json')):
            d = json.load(open(f))
            for v, x in d['variants'].items():
                rows.setdefault((d['dataset'], v), {})[d['seed']] = x
    return rows


def refs(a):
    return [f'K{k}' for k in a.ref_k.split(',') if k] + [v for v in a.ref_var.split(',') if v]


def roles(root):
    """Kế hoạch truy vấn chọn trên validation cho từng (corpus, B), từ val_best.json của run_semord.py."""
    p = os.path.join(root, 'val_best.json')
    if not os.path.exists(p):
        return {}
    return {tuple(k.split('/B')): tuple(v['config']) for k, v in json.load(open(p)).items()}


def summarize(a):
    S = load_semord(a.semord, a.nodes)
    V = load_vengram(a.vengram)
    sel = roles(a.semord)
    out = {'semord': {}, 'vengram': {}, 'paired': {}}
    for (ds, B, cfg), by in sorted(S.items()):
        if len(by) < len(SEEDS):
            continue
        xs = [by[s] for s in SEEDS]
        rec = [100 * x['recall'] for x in xs]
        msgs = [x['scalars'].get('overlay_runtime_hot_path_messages_mean', float('nan')) for x in xs]
        chosen = sel.get((ds, str(B)))
        role = ('chọn trên validation' if cfg == chosen else
                'mặc định' if cfg == (1, 10, 3, 2) else 'không được chọn' if chosen else '')
        out['semord'][f'{ds}/B{B}/{"-".join(map(str, cfg))}'] = {
            'dataset': ds, 'B': B, 'config': cfg, 'role': role,
            'recall_mean': st.mean(rec), 'recall_sd': st.stdev(rec), 'recall': rec,
            'recall_recomputed_mean': 100 * st.mean(x['parity']['recall_recomputed'] for x in xs),
            'peers_mean': st.mean(x['queried_nodes']['mean'] for x in xs),
            'peers_pct': 100 * st.mean(x['queried_nodes']['mean'] for x in xs) / a.nodes,
            'vectors_mean': st.mean(x['parity']['vectors_at_routed_mean'] for x in xs),
            'vectors_pct': 100 * st.mean(x['parity']['vectors_at_routed_mean'] for x in xs) / NDOCS[ds],
            'returned_mean': st.mean(x['parity'].get('returned_mean', float('nan')) for x in xs),
            'messages_mean': st.mean(msgs), 'rpc_equiv_mean': st.mean(msgs) / 2,
            'requests_mean': st.mean(x['scalars'].get('overlay_lookup_requests_mean', float('nan')) +
                                     x['scalars'].get('overlay_search_dispatch_requests_mean', float('nan')) for x in xs),
            'lookup_messages_mean': st.mean(x['scalars'].get('overlay_lookup_messages_mean', float('nan')) for x in xs),
            'dispatch_messages_mean': st.mean(x['scalars'].get('overlay_search_dispatch_messages_mean', float('nan')) for x in xs),
            'gt_distinct_nodes_mean': st.mean(x['primary_owner_gt_distinct_nodes']['mean'] for x in xs),
            'responsible_node_hit_mean': st.mean(x['responsible_node_hit'] for x in xs),
            'group_size_max_mean': st.mean(x['group_sizes']['max'] for x in xs),
            'group_size_mean': st.mean(x['group_sizes']['mean'] for x in xs),
            'storage_gini_mean': st.mean(x['group_sizes'].get('gini', float('nan')) for x in xs),
        }
    for (ds, v), by in sorted(V.items()):
        if len(by) < len(SEEDS):
            continue
        xs = [by[s] for s in SEEDS]
        rec = [x['recall_at_5'] for x in xs]
        out['vengram'][f'{ds}/{v}'] = {
            'dataset': ds, 'variant': v, 'recall_mean': st.mean(rec), 'recall_sd': st.stdev(rec), 'recall': rec,
            'peers_mean': st.mean(x['mean_contacted'] for x in xs),
            'peers_pct': st.mean(x['pct_contacted'] for x in xs),
            'vectors_mean': st.mean(x['n_unique_cand_mean'] for x in xs),
            'vectors_pct': 100 * st.mean(x['n_unique_cand_mean'] for x in xs) / NDOCS[ds],
            'rpc_mean': st.mean(x['mean_rpcs'] for x in xs),
            'rpc_routing_mean': st.mean(x['rpc_routing_mean'] for x in xs),
            'rpc_eval_mean': st.mean(x['rpc_eval_mean'] for x in xs),
            'metadata_gini_mean': st.mean(x['metadata_gini'] for x in xs),
        }
    # hiệu ghép theo seed: Semord ở mỗi cấu hình trừ V-Engram ở từng biến thể (K trong --ref-k, và
    # các biến thể trong --ref-var)
    for ks, s in out['semord'].items():
        for rv in refs(a):
            vk = out['vengram'].get(f"{s['dataset']}/{rv}")
            if not vk:
                continue
            m, lo, hi, pos = ci([x - y for x, y in zip(s['recall'], vk['recall'])])
            out['paired'].setdefault(ks, {})[f'minus_vengram_{rv}'] = [m, lo, hi, pos]
    return out


def fmt(x, d=1):
    return f'{x:.{d}f}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--semord', required=True)
    ap.add_argument('--vengram', required=True)
    ap.add_argument('--nodes', type=int, default=1000)
    ap.add_argument('--ref-k', default='2', help='K của V-Engram để tính hiệu ghép, ví dụ 4,2')
    ap.add_argument('--ref-var', default='', help='biến thể V-Engram khác để tính hiệu ghép, ví dụ L8_T5')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    o = summarize(a)
    json.dump(o, open(a.out, 'w'), indent=1)
    for ds in ('code', 'scifact'):
        print(f'== {ds} (N = {a.nodes}, 10 seed, query test)')
        print(f'{"hệ, ngân sách":34s} {"R@5":>12s} {"peer":>7s} {"peer %":>7s} {"vector":>8s} {"vec %":>6s} {"RPC":>7s}')
        for k, v in o['vengram'].items():
            if v['dataset'] != ds:
                continue
            print(f'{"V-Engram " + v["variant"]:34s} {fmt(v["recall_mean"]) + " ± " + fmt(v["recall_sd"]):>12s} '
                  f'{v["peers_mean"]:7.1f} {v["peers_pct"]:7.2f} {v["vectors_mean"]:8.0f} {v["vectors_pct"]:6.1f} {v["rpc_mean"]:7.0f}')
        for k, v in o['semord'].items():
            if v['dataset'] != ds:
                continue
            ps = ''
            for rv in refs(a):
                p = o['paired'].get(k, {}).get(f'minus_vengram_{rv}')
                if p:
                    ps += f' | − V-Engram {rv}: {p[0]:+.2f} [{p[1]:+.2f}, {p[2]:+.2f}] dương {p[3]}/10'
            rs = f' | {v["role"]}' if v.get('role') else ''
            print(f'{"Semord B" + str(v["B"]) + " " + str(v["config"]):34s} {fmt(v["recall_mean"]) + " ± " + fmt(v["recall_sd"]):>12s} '
                  f'{v["peers_mean"]:7.1f} {v["peers_pct"]:7.2f} {v["vectors_mean"]:8.0f} {v["vectors_pct"]:6.1f} {v["requests_mean"]:7.0f}{ps}{rs}')


if __name__ == '__main__':
    main()
