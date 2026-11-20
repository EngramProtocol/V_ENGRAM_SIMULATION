"""Danh sách job của đợt 3 (ppna-r1-dot3): phần iterative còn lại. Cùng định dạng job
và cùng bộ chạy ppna_r1/dot1/runner.py; mỗi job chạy ppna_r1/dot2/iterative.py (dựng
mạng một lần cho một (seed, corpus), chạy nhiều biến thể trên mạng đó).

Cấu hình chính: N = 10.000, L = 5, T = 8, K = 20, r = 1, c = 16, PQ m = 512, kappa = 30,
500 query, k-bucket dựng bằng join, Ripple Search stable/all, R_max = 15. Cùng 10 seed.
"""
import importlib.util
import json
import os

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
OUT = 'ppna_r1/out_dot3'
PY = os.environ.get('PY', 'python3')
ITER = 'ppna_r1/dot2/iterative.py'

# workload của R1-4: (tên dữ liệu, biến thể PQ)
WORKLOADS = [('squad', 'm512'), ('code_e5', 'm512'), ('scifact_e5', 'm512'), ('code_jina', 'm448')]

GROUPS = {
    'tk':   'Bảng 5 trên iterative: T ∈ {1, 3, 5, 12} (K = 20) và K ∈ {10, 40, 80} (T = 8), code',
    'ws50': '50.000 peer (code100k), K = 100 và K = 20',
    'wl':   'Workload R1-4 (SQuAD, e5 code, e5 SciFact, jina code): semantic và random equal peers',
    'ref':  'Join đầy đủ như Kademlia gốc: hai vòng làm mới k-bucket sau join, code và SciFact',
    'lshf': 'Bucket-LSH với ingest chạy hết ngân sách (exhaust/all, R_max 15), code và SciFact',
    # bản sao mọi thí nghiệm iterative với join đầy đủ (join + một vòng làm mới k-bucket)
    'sem_r':  'Join đầy đủ: như nhóm sem của đợt 2 (Bảng 7, control, margin, cặp c, oracle, mất peer)',
    'lsh_r':  'Join đầy đủ: Bucket-LSH T = 8, b chọn trên validation',
    'loss_r': 'Join đầy đủ: r = 2 và 3, không mất và mất 30% peer (code)',
    'ws25_r': 'Join đầy đủ: 25.000 peer (code50k), K = 50 và K = 20',
    'ws50_r': 'Join đầy đủ: 50.000 peer (code100k), K = 100 và K = 20',
    'tk_r':   'Join đầy đủ: Bảng 5 trên iterative (code)',
    'wl_r':   'Join đầy đủ: workload R1-4, semantic và random equal peers',
}
JR = ['--join-refresh', '1']


def _load(name, rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', rel)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D2 = _load('dot2_jobs', 'dot2/jobs.py')
B_LSH_T8 = D2.B_LSH_T8


def _needs(ds, pq='m512'):
    D = f'data/{ds}'
    return [f'{D}_corpus_embeddings.npy', f'{D}_query_embeddings.npy', f'{D}_ground_truth.json',
            f'{D}_pq_codes_{pq}.npy', f'{D}_pq_codebook_{pq}.npy']


def it(group, name, plan, ds, seed, nodes=10000, est=600, args=(), out_root=OUT, nq=500,
       num_files=None, prio=1, pq='m512'):
    out = f'{out_root}/{group}/{name}_s{seed}.json'
    cmd = [PY, '-u', ITER, '--plan', plan, '--dataset', ds, '--nodes', str(nodes),
           '--seed', str(seed), '--nq', str(nq), '--pq', pq]
    if num_files:
        cmd += ['--num-files', str(num_files)]
    cmd += list(args) + ['--out', out]
    return {'id': f'{group}/{name}_s{seed}', 'group': group, 'kind': 'iter', 'cmd': cmd,
            'env': {}, 'out': out, 'needs': _needs(ds, pq), 'prio': prio, 'est': est,
            'big': nodes >= 35000, 'timeout': 12 * 3600, 'seed': seed}


def build(seeds=None, groups=None):
    seeds = seeds or SEEDS
    J = []

    def want(g):
        return groups is None or g in groups

    for s in seeds:
        si = SEEDS.index(s)
        if want('ws50'):     # dài nhất: chạy trước
            J.append(it('ws50', 'code100k_N50000', 'ws', 'code100k', s, nodes=50000, est=1500,
                        prio=0, args=['--k', '100', '--extra-k', '20']))
        if want('tk'):
            J.append(it('tk', 'code', 'tk', 'code', s, est=600))
        if want('ref'):
            J.append(it('ref', 'code', 'refresh', 'code', s, est=800, args=['--refresh-rounds', '2']))
            J.append(it('ref', 'scifact', 'refresh', 'scifact', s, est=500, args=['--refresh-rounds', '2']))
        if want('wl'):
            for ds, pq in WORKLOADS:
                J.append(it('wl', ds, 'wl', ds, s, pq=pq, est=100 if 'scifact' in ds else 200))
        if want('lshf'):
            for ds in ('code', 'scifact'):
                J.append(it('lshf', f'{ds}_T8', 'lsh', ds, s, est=200 if ds == 'code' else 100,
                            args=['--lsh-b', str(B_LSH_T8[ds][si]), '--T', '8',
                                  '--ingest-rule', 'exhaust,all,15']))
        # ---- bản sao với join đầy đủ; 50.000 peer chạy trước vì dài nhất ----
        if want('ws50_r'):
            J.append(it('ws50_r', 'code100k_N50000', 'ws', 'code100k', s, nodes=50000, est=2300,
                        prio=0, args=['--k', '100', '--extra-k', '20'] + JR))
        if want('ws25_r'):
            J.append(it('ws25_r', 'code50k_N25000', 'ws', 'code50k', s, nodes=25000, est=900,
                        prio=1, args=['--k', '50', '--extra-k', '20'] + JR))
        if want('sem_r'):
            J.append(it('sem_r', 'code', 'sem', 'code', s, est=1000, args=['--loss', '0.20,0.30'] + JR))
            J.append(it('sem_r', 'scifact', 'sem', 'scifact', s, est=550, args=JR))
        if want('lsh_r'):
            for ds in ('code', 'scifact'):
                J.append(it('lsh_r', f'{ds}_T8', 'lsh', ds, s, est=250 if ds == 'code' else 150,
                            args=['--lsh-b', str(B_LSH_T8[ds][si]), '--T', '8'] + JR))
        if want('loss_r'):
            J.append(it('loss_r', 'code_r23', 'loss', 'code', s, est=450,
                        args=['--loss', '0.30', '--r-list', '2,3'] + JR))
        if want('tk_r'):
            J.append(it('tk_r', 'code', 'tk', 'code', s, est=650, args=JR))
        if want('wl_r'):
            for ds, pq in WORKLOADS:
                J.append(it('wl_r', ds, 'wl', ds, s, pq=pq, est=150 if 'scifact' in ds else 250, args=JR))
    ids = [j['id'] for j in J]
    assert len(ids) == len(set(ids)), 'trùng id job'
    return J


def build_smoke(root='ppna_r1/logs_dot3/smoke'):
    """Bản thu nhỏ của mọi kiểu job (2.000 peer, 4.000 object, 10 query)."""
    s = 1
    o = f'{root}/out'
    small = dict(nodes=2000, nq=10, num_files=4000, out_root=o, prio=0)
    J = [
        it('sm', 'tk_code', 'tk', 'code', s, **small),
        it('sm', 'ws_code100k', 'ws', 'code100k', s, args=['--k', '100', '--extra-k', '20'], **small),
        it('sm', 'ref_scifact', 'refresh', 'scifact', s, args=['--refresh-rounds', '2'], **small),
        it('sm', 'lshf_code', 'lsh', 'code', s,
           args=['--lsh-b', '10', '--T', '8', '--ingest-rule', 'exhaust,all,15'], **small),
    ]
    J += [it('sm', f'wl_{ds}', 'wl', ds, s, pq=pq, **small) for ds, pq in WORKLOADS]
    J.append(it('sm', 'sem_r_code', 'sem', 'code', s, args=['--loss', '0.30'] + JR, **small))
    for j in J:
        j['timeout'] = 3600
        j['est'] = 120
    return J


if __name__ == '__main__':
    import argparse
    import collections
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--write', metavar='FILE', help='ghi danh sách job ra JSON lines')
    a = ap.parse_args()
    J = build_smoke() if a.smoke else build()
    if a.write:
        with open(a.write, 'w', encoding='utf-8') as fh:
            for j in J:
                fh.write(json.dumps(j, ensure_ascii=False) + '\n')
    cnt = collections.Counter(j['group'] for j in J)
    est = collections.Counter()
    for j in J:
        est[j['group']] += j['est']
    for g in cnt:
        print(f'{g:6s} {cnt[g]:5d} job  ~{est[g] / 3600:5.1f} giờ một nhân  {GROUPS.get(g, "")}')
    print(f'TỔNG   {len(J):5d} job  ~{sum(est.values()) / 3600:5.1f} giờ một nhân')
