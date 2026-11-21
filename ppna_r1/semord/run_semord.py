"""Chạy Semord (artifact Vortex_system của tác giả, VHash huấn luyện bằng LearnedHash) trên code và
SciFact, và ghi Recall@5, số peer liên lạc, số vector ở các peer đó, số message mỗi query.

Simulator của artifact dựng underlay full mesh nên bộ nhớ tăng theo N^2 (0,35 GB ở 500 node,
0,79 GB ở 1.000, 2,4 GB ở 2.000; ước khoảng 50 GB ở 10.000). Vì vậy so sánh đặt ở N = 1.000 peer,
mức lớn nhất trong dải tác giả đánh giá (32 đến 1.024), và V-Engram chạy ở cùng N với K = N/500.

Bước:
  val   quét vài tổ hợp tham số lập kế hoạch truy vấn của Semord (rapid ring hops, số vùng, số peer
        mỗi vùng) trên query validation, seed đầu, cho từng ngân sách B = max_query_nodes; giữ tổ
        hợp có recall validation cao nhất. Không dùng query test.
  test  chạy query test với tổ hợp đã chọn (và tổ hợp mặc định của artifact), đủ 10 seed; mỗi seed
        dùng model VHash huấn luyện với seed đó.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
BUDGETS = [16, 49, 225]
DEFAULT = (1, 10, 3, 2)   # rapid hops, extended centroids, top nodes, fallback nodes (mặc định)


def grid_for_budget(B):
    """Tổ hợp thử trên validation. Mặc định của artifact chứa tối đa khoảng 64 peer, nên với B lớn
    cần thêm vùng hoặc thêm peer mỗi vùng. Mở rộng vòng ring quanh owner (rapid hops) đã thử ở
    B = 16 trên code: kém hơn mặc định (52,2 và 64,3 so với 65,3) và chậm gấp ba, nên không quét.
    (1, 64, 32, 2) và (1, 64, B, 2) tra trọn từng vùng khi vùng lớn: mỗi vùng (centroid) có khoảng
    N/K node, tức khoảng 31 node với SciFact ở 2.000 node, nên 16 peer mỗi vùng chỉ phủ nửa vùng;
    (1, 64, B, 2) bỏ hẳn giới hạn số peer mỗi vùng, tra lần lượt từng vùng theo thứ hạng tới hết
    ngân sách. Với vùng nhỏ các kế hoạch này gần như trùng (1, 64, 16, 2); khi hoà recall, kế hoạch
    đứng trước trong danh sách được chọn."""
    g = [DEFAULT,
         (1, max(10, math.ceil(B / 4)), 3, 2),             # thêm vùng
         (1, 10, max(3, math.ceil(B / 12)), 2),            # thêm peer mỗi vùng
         (1, max(10, math.ceil(B / 8)), max(3, math.ceil(B / 24)), 2),
         (1, 32, 8, 2),
         (1, 64, 16, 2),
         (1, 64, 32, 2),
         (1, 64, B, 2)]
    out = []
    for x in g:
        if x not in out:
            out.append(x)
    return out


def parse_log(path):
    res = {'scalars': {}}
    with open(path) as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            e = ev.get('event')
            if e == 'recall':
                res['recall'] = ev['value']
                res['gt_k'] = ev['k']
            elif e == 'queried_nodes':
                res['queried_nodes'] = ev['stats']
            elif e == 'group_sizes':
                sizes = ev['sizes']
                res['group_sizes'] = {'n': len(sizes), 'mean': sum(sizes) / len(sizes),
                                      'max': max(sizes), 'min': min(sizes),
                                      'empty': sum(1 for s in sizes if s == 0)}
                res['_sizes'] = sizes
            elif e in ('primary_owner_gt_distinct_nodes', 'primary_owner_gt_nodes_needed'):
                res[e] = ev['stats']
            elif e == 'primary_owner_responsible_node_hit':
                res['responsible_node_hit'] = ev['value']
            elif e == 'scalar':
                res['scalars'][ev['name']] = ev['value']
            elif e == 'query_parity':
                res.setdefault('_parity', []).append(ev)
            elif e == 'timing' and ev.get('phase') == 'total_wall':
                res['bench_wall_seconds'] = ev.get('seconds')
    return res


def summarize_parity(events, sizes, gt_path, k=5):
    """Từ danh sách peer và kết quả của từng query: số vector ở các peer được liên lạc, số peer
    không rỗng, và Recall@5 tính lại độc lập với bench."""
    import numpy as np
    raw = np.fromfile(gt_path, dtype=np.int32)
    kk = int(raw[0])
    G = raw.reshape(-1, kk + 1)[:, 1:]
    vec, nonempty, rec, returned = [], [], [], []
    for ev in events:
        groups = ev['routed_groups']
        v = [sizes[g] for g in groups]
        vec.append(sum(v))
        nonempty.append(sum(1 for x in v if x > 0))
        returned.append(sum(min(k, x) for x in v))     # mỗi peer trả tối đa sub-k = 5 kết quả
        q = ev['query_index']
        pred = [i for i in ev['result_indices'][:k] if i >= 0]
        rec.append(len(set(pred) & set(G[q, :k].tolist())) / k)
    m = lambda x: float(sum(x) / len(x)) if x else None
    return {'n_queries': len(events), 'vectors_at_routed_mean': m(vec),
            'nonempty_routed_mean': m(nonempty), 'returned_mean': m(returned),
            'recall_recomputed': m(rec)}


def job_tag(ds, seed, qset, B, cfg, N):
    r, c, t, f = cfg
    return f'{ds}_s{seed}_{qset}_N{N}_B{B}_r{r}_c{c}_t{t}_f{f}'


def method_config(a, ds, seed):
    """Cấu hình VHash đã dùng để huấn luyện model vortex_v1_<ds>_s<seed> (semord_config.json)."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(a.bench))), 'methods',
                     f'vortex_v1_{ds}{getattr(a, "method_suffix", "")}_s{seed}', 'semord_config.json')
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return None


def run_one(a, ds, seed, qset, B, cfg, out_dir):
    tag = job_tag(ds, seed, qset, B, cfg, a.nodes)
    out = os.path.join(out_dir, tag + '.json')
    vcfg = method_config(a, ds, seed)
    if os.path.exists(out):
        old = json.load(open(out))
        if old.get('vhash_config') == vcfg:    # chỉ dùng lại kết quả của đúng model hiện tại
            return old
    log = os.path.join(out_dir, 'logs', tag + '.jsonl')
    os.makedirs(os.path.dirname(log), exist_ok=True)
    if os.path.exists(log):
        os.remove(log)
    r, c, t, f = cfg
    D = os.path.join(a.data, ds)
    q = f'{D}/{ds}_val_query.fvecs' if qset == 'val' else f'{D}/{ds}_query.fvecs'
    g = f'{D}/{ds}_val_groundtruth.ivecs' if qset == 'val' else f'{D}/{ds}_groundtruth.ivecs'
    cmd = [a.bench, '--base', f'{D}/{ds}_base.fvecs', '--query', q, '--groundtruth', g,
           '--method', f'vortex_v1_{ds}{getattr(a, "method_suffix", "")}_s{seed}', '--num-groups', str(a.nodes),
           '--seed', str(seed),
           '--final-k', '5', '--sub-k', '5', '--gt-k', '5',
           '--fuzzy-query-extended-hops', str(r), '--extended-center-groups', str(c),
           '--method-param', f'max_query_nodes={B}',
           '--method-param', f'centroid_probe_top_nodes={t}',
           '--method-param', f'centroid_probe_range_fallback={f}',
           '--experiment', f'ppna_semord_{ds}', '--log', log]
    env = dict(os.environ, VBENCH_LOG_QUERY_PARITY='1', OMP_NUM_THREADS='1')
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        sys.stderr.write(p.stdout[-1500:] + p.stderr[-3000:])
        raise RuntimeError(f'vortex_bench lỗi ({p.returncode}): {tag}')
    res = parse_log(log)
    sizes = res.pop('_sizes')
    srt = sorted(sizes)
    res['group_sizes']['gini'] = (2 * sum((i + 1) * v for i, v in enumerate(srt)) / (len(srt) * sum(srt))
                                  - (len(srt) + 1) / len(srt))
    res['parity'] = summarize_parity(res.pop('_parity', []), sizes, g)
    res.update({'dataset': ds, 'seed': seed, 'query_set': qset, 'B': B, 'rapid_hops': r,
                'extended_centroids': c, 'centroid_top_nodes': t, 'centroid_fallback_nodes': f,
                'nodes': a.nodes, 'seconds': round(time.time() - t0, 2), 'cmd': cmd,
                'vhash_config': vcfg})
    tmp = out + '.tmp'
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, out)
    os.remove(log)      # log đầy đủ rất lớn; giữ bản tóm tắt JSON
    return res


def run_jobs(a, jobs):
    def go(j):
        res = run_one(a, *j)
        print(f"{j[0]} s{j[1]} {j[2]} B{j[3]} cfg{j[4]} R@5 {100 * res['recall']:.2f} "
              f"peer {res['queried_nodes']['mean']:.1f} vec {res['parity']['vectors_at_routed_mean']:.0f} "
              f"{res['seconds']:.0f}s", flush=True)
        return res
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        return list(ex.map(go, jobs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench', required=True)
    ap.add_argument('--data', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--stage', choices=['val', 'test', 'one'], required=True)
    ap.add_argument('--datasets', default='code,scifact')
    ap.add_argument('--budgets', default=','.join(str(b) for b in BUDGETS))
    ap.add_argument('--test-budgets', default='16,49,225')
    ap.add_argument('--seeds', default=','.join(str(s) for s in SEEDS))
    ap.add_argument('--nodes', type=int, default=1000)
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--one', default='', help='B,r,c,t,f cho --stage one')
    ap.add_argument('--method-suffix', default='', help='hậu tố tên model, ví dụ _n2000')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    seeds = [int(x) for x in a.seeds.split(',') if x]
    dss = a.datasets.split(',')
    if a.stage == 'one':
        B, r, c, t, f = (int(x) for x in a.one.split(','))
        run_jobs(a, [(ds, seeds[0], 'val', B, (r, c, t, f), a.out) for ds in dss])
        return
    if a.stage == 'val':
        budgets = [int(x) for x in a.budgets.split(',') if x]
        jobs = [(ds, SEEDS[0], 'val', B, cfg, a.out) for ds in dss for B in budgets
                for cfg in grid_for_budget(B)]
        res = run_jobs(a, jobs)
        best = {}
        for ds in dss:
            for B in budgets:
                rows = [x for x in res if x['dataset'] == ds and x['B'] == B]
                rows.sort(key=lambda x: (x['recall'], -x['queried_nodes']['mean']), reverse=True)
                top = rows[0]
                dflt = [x for x in rows if (x['rapid_hops'], x['extended_centroids'],
                                            x['centroid_top_nodes'], x['centroid_fallback_nodes']) == DEFAULT]
                best[f'{ds}/B{B}'] = {
                    'config': [top['rapid_hops'], top['extended_centroids'], top['centroid_top_nodes'],
                               top['centroid_fallback_nodes']],
                    'val_recall': top['recall'], 'val_queried_mean': top['queried_nodes']['mean'],
                    'default_val_recall': dflt[0]['recall'] if dflt else None,
                    'grid': [[x['rapid_hops'], x['extended_centroids'], x['centroid_top_nodes'],
                              x['centroid_fallback_nodes'], x['recall'], x['queried_nodes']['mean']]
                             for x in rows]}
        json.dump(best, open(os.path.join(a.out, 'val_best.json'), 'w'), indent=1)
        print(json.dumps({k: (v['config'], round(v['val_recall'], 4), v['default_val_recall'])
                          for k, v in best.items()}, indent=1))
        return
    best = json.load(open(os.path.join(a.out, 'val_best.json')))
    jobs = []
    for ds in dss:
        for B in [int(x) for x in a.test_budgets.split(',') if x]:
            cfg = tuple(best[f'{ds}/B{B}']['config'])
            extra = [DEFAULT] if (cfg != DEFAULT and B <= 64) else []   # mặc định chứa tối đa ~64 peer
            for cf in ([cfg] + extra):
                jobs += [(ds, s, 'test', B, cf, a.out) for s in seeds]
    run_jobs(a, jobs)


if __name__ == '__main__':
    main()
