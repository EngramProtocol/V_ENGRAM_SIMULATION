"""Danh sách job của đợt 5 (ppna-r1-dot5): churn trên mô hình iterative, ba cấu hình của Bảng 10.
Cùng định dạng job và cùng bộ chạy ppna_r1/dot1/runner.py.

- churn_it: ppna_r1/dot5/churn_iter.py, ba cấu hình (r = 1 không sửa, r = 1 sửa mỗi 480 phút, r = 4 sửa
  mỗi 1.320 phút), code, N = 10.000, 200 query, phiên Weibull median 120 phút, thời lượng như đợt 1
  (max(6 median, 3 chu kỳ sửa)), 10 seed. Số của mô hình lý tưởng để ghép cặp là nhóm churn của đợt 1
  (ppna_r1/out_dot1/churn), cùng lệnh và cùng seed.
"""
import importlib.util
import json
import os

OUT = 'ppna_r1/out_dot5'
PY = os.environ.get('PY', 'python3')
SCRIPT = 'ppna_r1/dot5/churn_iter.py'

GROUPS = {
    'churn_it': 'Bảng 10 trên mô hình iterative: churn, ba cấu hình, code, 10 seed',
}


def _load(name, rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', rel)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D1 = _load('dot1_jobs', 'dot1/jobs.py')
SEEDS = D1.SEEDS
CHURN_CONFIGS = D1.CHURN_CONFIGS          # [(1, 0), (1, 480), (4, 1320)]
# thời gian (giây, một nhân) theo cấu hình, đo trên máy 2 nhân chạy 2 job song song; dùng để xếp job dài
# chạy trước và ước thời gian còn lại
EST = {(1, 0): 650, (1, 480): 1250, (4, 1320): 2500}


def ch(r, rep, seed, nodes=10000, nq=200, ses=120, duration=None, ds='code', prio=1, out_root=OUT,
       group='churn_it', num_files=None, est=None, extra=()):
    dur = duration if duration is not None else max(6 * ses, 3 * rep)
    out = f'{out_root}/{group}/r{r}_rep{rep}_s{seed}.json'
    cmd = [PY, '-u', SCRIPT, '--dataset', ds, '--nodes', str(nodes), '--nq', str(nq),
           '--median-session', str(ses), '--duration', str(dur), '--meta-anchors', str(r),
           '--repair-interval', str(rep), '--seed', str(seed)]
    if num_files:
        cmd += ['--num-files', str(num_files)]
    cmd += list(extra) + ['--out', out]
    return {'id': f'{group}/r{r}_rep{rep}_s{seed}', 'group': group, 'kind': 'churn_it', 'cmd': cmd,
            'env': {}, 'out': out, 'needs': D1._data(ds, 'm512'), 'prio': prio,
            'est': est if est is not None else EST.get((r, rep), 8000), 'big': False,
            'timeout': 48 * 3600, 'seed': seed}


def build(seeds=None):
    J = []
    for s in seeds or SEEDS:
        for r, rep in CHURN_CONFIGS:
            # seed đầu chạy trước (cả ba cấu hình) để có sớm một bộ số kiểm tra; còn lại job dài trước
            J.append(ch(r, rep, s, prio=0 if s == SEEDS[0] else 1))
    ids = [j['id'] for j in J]
    assert len(ids) == len(set(ids)), 'trùng id job'
    return J


def build_smoke(root='ppna_r1/logs_dot5/smoke'):
    """Bản thu nhỏ (2.000 peer, 2.000 object SciFact, 10 query, thời lượng ngắn) qua mọi nhánh của mã:
    không sửa, sửa với r = 1, sửa với r = 2."""
    o = f'{root}/out'
    small = dict(nodes=2000, nq=10, ds='scifact', num_files=2000, out_root=o, group='sm', prio=0, est=150)
    J = [ch(1, 0, 1, duration=360, **small), ch(2, 120, 1, duration=360, **small),
         ch(1, 120, 1, duration=360, **small)]
    for j in J:
        j['timeout'] = 3600
    return J


def resume_test(root='ppna_r1/logs_dot5/smoke'):
    """Chạy lại job smoke r = 1, sửa mỗi 120 phút: lần đầu dừng giữa chừng (checkpoint mỗi epoch, thoát
    sau 15 giây), lần hai chạy tiếp từ checkpoint. aggregate.py --smoke-check so kết quả với job liền mạch."""
    import subprocess
    j = [x for x in build_smoke(root) if x['id'] == 'sm/r1_rep120_s1'][0]
    out = f'{root}/out/resume_test.json'
    cmd = j['cmd'][:-1] + [out]
    for p in (out, out + '.ckpt'):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               PYTHONUNBUFFERED='1')
    with open(f'{root}/resume_test.log', 'w', encoding='utf-8') as log:
        rc1 = subprocess.call(cmd + ['--ckpt-every', '0', '--stop-after', '15'], stdout=log,
                              stderr=subprocess.STDOUT, env=env)
        rc2 = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
    print(f'kiểm thử chạy tiếp: lần đầu mã thoát {rc1} (cần 75), lần hai {rc2} (cần 0)')
    return 0 if (rc1, rc2) == (75, 0) else 1


if __name__ == '__main__':
    import argparse
    import collections
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--resume-test', action='store_true', help='chạy kiểm thử chạy tiếp từ checkpoint')
    ap.add_argument('--write', metavar='FILE', help='ghi danh sách job ra JSON lines')
    a = ap.parse_args()
    if a.resume_test:
        raise SystemExit(resume_test())
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
        print(f'{g:9s} {cnt[g]:4d} job  ~{est[g] / 3600:5.1f} giờ một nhân  {GROUPS.get(g, "")}')
    print(f'TỔNG      {len(J):4d} job  ~{sum(est.values()) / 3600:5.1f} giờ một nhân')
