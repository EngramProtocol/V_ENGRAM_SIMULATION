"""Danh sách job của đợt 2 (ppna-r1-dot2). Cùng định dạng job với đợt 1 (xem
ppna_r1/dot1/jobs.py), chạy bằng cùng bộ chạy ppna_r1/dot1/runner.py.

Phần iterative dùng ppna_r1/dot2/iterative.py: mỗi job dựng mạng một lần cho một
(seed, corpus) rồi chạy nhiều biến thể truy vấn trên mạng đó; một file JSON mỗi job.
Phần lý tưởng dùng main_simulation_v2.py như đợt 1.

Cấu hình chính: N = 10.000, L = 5, T = 8, K = 20, r = 1, c = 16, PQ m = 512, kappa = 30,
500 query, Achlioptas chuẩn hoá cột, k-bucket dựng bằng join, Ripple Search stable/all,
R_max = 15. Cùng 10 seed với đợt 1.
"""
import importlib.util
import json
import os

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
OUT = 'ppna_r1/out_dot2'
PY = os.environ.get('PY', 'python3')
ITER = 'ppna_r1/dot2/iterative.py'

# b_LSH chọn trên validation ở đợt 1 cho T = 8, theo thứ tự SEEDS
# (ppna_r1/dot1_summary.json, table6 -> b_sel). check_b() kiểm lại trên server.
B_LSH_T8 = {'code': [12, 10, 11, 12, 10, 11, 11, 11, 10, 12],
            'scifact': [12, 10, 11, 11, 11, 9, 11, 11, 10, 10]}

GROUPS = {
    'sem':   'Iterative, cấu hình chính và các biến thể chỉ đổi truy vấn: Bảng 7 (R_max 15, 30), '
             'bốn control, margin ablation, (c = 9, T = 5), truy vấn oracle; code thêm mất 20%, 30% peer',
    'dec':   'Iterative, phân tách khoảng cách: đặt record oracle, ingest hết ngân sách, bảng đầy đủ',
    'lsh':   'Iterative, Bucket-LSH T = 8 với b chọn trên validation ở đợt 1',
    'loss':  'Iterative, r = 2 và 3: không mất và mất 30% peer (code)',
    'ws':    'Iterative, 25.000 peer (code50k), K = 50 và K = 20',
    'gpt':   'Lý tưởng, Gaussian kèm thống kê từng bảng chiếu, hai corpus',
    'jina':  'Lý tưởng, jina-code-embeddings-0.5b: T = 12; K = 40, 80; L = 8; (L = 8, T = 5)',
}


def _load_dot1_jobs():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dot1', 'jobs.py')
    spec = importlib.util.spec_from_file_location('dot1_jobs', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D1 = _load_dot1_jobs()


def _needs(ds):
    D = f'data/{ds}'
    return [f'{D}_corpus_embeddings.npy', f'{D}_query_embeddings.npy', f'{D}_ground_truth.json',
            f'{D}_pq_codes_m512.npy', f'{D}_pq_codebook_m512.npy']


def it(group, name, plan, ds, seed, nodes=10000, est=900, args=(), out_root=OUT, nq=500,
       num_files=None, prio=1):
    out = f'{out_root}/{group}/{name}_s{seed}.json'
    cmd = [PY, '-u', ITER, '--plan', plan, '--dataset', ds, '--nodes', str(nodes),
           '--seed', str(seed), '--nq', str(nq)]
    if num_files:
        cmd += ['--num-files', str(num_files)]
    cmd += list(args) + ['--out', out]
    big = nodes >= 35000
    return {'id': f'{group}/{name}_s{seed}', 'group': group, 'kind': 'iter', 'cmd': cmd,
            'env': {}, 'out': out, 'needs': _needs(ds), 'prio': prio, 'est': est,
            'big': big, 'timeout': 12 * 3600, 'seed': seed}


def v2(group, name, ds, seed, out_root=OUT, **kw):
    return D1.v2(group, name, ds, seed, out_root=out_root, **kw)


def build(seeds=None, groups=None):
    seeds = seeds or SEEDS
    J = []

    def want(g):
        return groups is None or g in groups

    for i, s in enumerate(seeds):
        si = SEEDS.index(s) if s in SEEDS else None
        if want('sem'):
            J.append(it('sem', 'code', 'sem', 'code', s, est=870, args=['--loss', '0.20,0.30']))
            J.append(it('sem', 'scifact', 'sem', 'scifact', s, est=450))
        if want('dec'):
            J.append(it('dec', 'code', 'dec', 'code', s, est=690))
            J.append(it('dec', 'scifact', 'dec', 'scifact', s, est=300))
        if want('lsh') and si is not None:
            for ds in ('code', 'scifact'):
                b = B_LSH_T8[ds][si]
                J.append(it('lsh', f'{ds}_T8', 'lsh', ds, s, est=150 if ds == 'code' else 70,
                            args=['--lsh-b', str(b), '--T', '8']))
        if want('loss'):
            J.append(it('loss', 'code_r23', 'loss', 'code', s, est=330,
                        args=['--loss', '0.30', '--r-list', '2,3']))
        if want('ws'):
            J.append(it('ws', 'code50k_N25000', 'ws', 'code50k', s, nodes=25000, est=420,
                        args=['--k', '50', '--extra-k', '20']))
        if want('gpt'):
            for ds in ('code', 'scifact'):
                J.append(v2('gpt', f'{ds}_gauss_semantic', ds, s, family='gaussian',
                            per_table=True, prio=2, est=60))
        if want('jina'):
            for lab, kw in (('T12_K20', dict(T=12)), ('T8_K40', dict(K=40)), ('T8_K80', dict(K=80)),
                            ('L8', dict(L=8)), ('L8_T5', dict(L=8, T=5))):
                J.append(v2('jina', f'code_jina_{lab}', 'code_jina', s, pq='m448', prio=2,
                            est=50 + (30 if kw.get('K', 20) > 20 else 0), **kw))
    ids = [j['id'] for j in J]
    assert len(ids) == len(set(ids)), 'trùng id job'
    return J


def build_smoke(root='ppna_r1/logs_dot2/smoke'):
    """Bản thu nhỏ của mọi kiểu job, và hai job đo thời gian, bộ nhớ ở 25.000 và
    50.000 peer (dựng mạng đủ, ingest 2.000 object, 20 query) để ước đợt 3."""
    s = 1
    o = f'{root}/out'
    small = dict(nodes=2000, nq=10, num_files=4000, out_root=o)
    J = [
        it('sm', 'sem_code', 'sem', 'code', s, args=['--loss', '0.20,0.30'], **small),
        it('sm', 'dec_scifact', 'dec', 'scifact', s, **small),
        it('sm', 'lsh_code', 'lsh', 'code', s, args=['--lsh-b', '10', '--T', '8'], **small),
        it('sm', 'loss_code', 'loss', 'code', s, args=['--loss', '0.30', '--r-list', '2,3'], **small),
        it('sm', 'ws_code50k', 'ws', 'code50k', s, args=['--k', '50', '--extra-k', '20'], **small),
        v2('sm', 'v2_gauss_pt', 'scifact', s, nodes=2000, nq=5, family='gaussian', per_table=True,
           out_root=o),
        v2('sm', 'v2_jina_L8_T5', 'code_jina', s, nodes=2000, nq=5, pq='m448', L=8, T=5, out_root=o),
        it('sm', 'probe_N25000', 'probe', 'code50k', s, nodes=25000, nq=20, out_root=o,
           args=['--k', '50', '--probe-docs', '2000']),
        it('sm', 'probe_N50000', 'probe', 'code100k', s, nodes=50000, nq=20, out_root=o,
           args=['--k', '100', '--probe-docs', '2000']),
    ]
    for j in J:
        j['prio'], j['big'] = 0, False
        j['timeout'] = 3600
        j['est'] = 600 if 'probe' in j['id'] else 120
    return J


def check_b(summary_path):
    """So B_LSH_T8 với lựa chọn của đợt 1 trong dot1_summary.json. Trả list lỗi."""
    if not os.path.exists(summary_path):
        return [f'không thấy {summary_path}; không kiểm được b_LSH (dùng giá trị ghi trong jobs.py)']
    with open(summary_path, encoding='utf-8') as fh:
        t6 = json.load(fh).get('table6', {})
    err = []
    for ds, b in B_LSH_T8.items():
        got = t6.get(f'{ds}/T8', {}).get('b_sel')
        if got != b:
            err.append(f'{ds}: jobs.py {b} khác dot1_summary.json {got}')
    return err


if __name__ == '__main__':
    import argparse
    import collections
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--write', metavar='FILE', help='ghi danh sách job ra JSON lines')
    ap.add_argument('--check-b', metavar='SUMMARY', help='kiểm b_LSH với dot1_summary.json')
    a = ap.parse_args()
    if a.check_b:
        errs = check_b(a.check_b)
        for e in errs:
            print('b_LSH:', e)
        if any('khác' in e for e in errs):
            raise SystemExit(1)
        if not errs:
            print('b_LSH: khớp dot1_summary.json')
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
