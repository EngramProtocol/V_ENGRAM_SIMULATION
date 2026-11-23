"""Danh sách job của đợt 6 (ppna-r1-dot6): availability của Bảng 9 trên overlay k-bucket với join
đầy đủ. Cùng định dạng job và cùng bộ chạy ppna_r1/dot1/runner.py.

- old:  đúng lệnh nhóm avail của đợt 1 (join cũ, r = 1, 2, 3, 10 seed, mất 0..50% peer), thêm
        RECORD_KILLS=1 để ghi ID peer bị tắt ở từng mức. Ghi thêm không dùng số ngẫu nhiên nào, nên
        mọi số đo phải trùng file của đợt 1 (ppna_r1/out_dot1/avail).
- full: cùng lệnh, thêm JOIN_REFRESH=1 (join đầy đủ, như --join-refresh 1 của các đợt iterative) và
        KILL_FROM = file kết quả nhóm old cùng r, cùng seed, nên hai cách dựng mạng được đo trên đúng
        cùng tập peer chết. Job full cần file của job old tương ứng (trường needs). Bảng định tuyến
        sau vòng làm mới không phụ thuộc r, nên chia hai nhóm chạy nối tiếp: full_a (r = 1) làm mới
        và ghi k-bucket vào REFRESH_CACHE (một file mỗi seed), full_b (r = 2, 3) nạp lại file đó.
        Kết quả cả hai nhóm ghi vào cùng thư mục full/.
- chk:  r = 1 của seed đầu, nạp k-bucket từ file của full_a, ghi vào chk/. Phải trùng từng số với
        job full cùng r, cùng seed (làm mới thật); aggregate.py kiểm.
- sm:   smoke, mạng 800 peer: join cũ, join đầy đủ (làm mới, ghi bộ đệm) và join đầy đủ nạp bộ đệm.
"""
import importlib.util
import json
import os

OUT = 'ppna_r1/out_dot6'
SEEDS_ENV = os.environ.get('SEEDS')

GROUPS = {
    'old': 'Bảng 9, join cũ, như nhóm avail của đợt 1, có ghi tập peer chết',
    'full_a': 'Bảng 9, join đầy đủ, r = 1: làm mới k-bucket và ghi bộ đệm, phát lại tập peer chết',
    'full_b': 'Bảng 9, join đầy đủ, r = 2, 3: nạp k-bucket đã làm mới, phát lại tập peer chết',
    'chk': 'kiểm bộ đệm: r = 1 của seed đầu, nạp k-bucket, phải trùng job full cùng r, cùng seed',
    'sm': 'smoke: 800 peer, join cũ, join đầy đủ, join đầy đủ nạp bộ đệm',
}


def _load(name, rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', rel)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D1 = _load('dot1_jobs', 'dot1/jobs.py')
SEEDS = [int(s) for s in SEEDS_ENV.split(',')] if SEEDS_ENV else D1.SEEDS
# thời gian một job (giây), đo trên máy 2 nhân chạy 2 job song song: join cũ; join đầy đủ có làm
# mới k-bucket (vòng làm mới khoảng 2 phút); join đầy đủ nạp k-bucket từ bộ đệm
EST = {'old': 330, 'full_a': 950, 'full_b': 860}


def cache_path(seed, out_root=OUT, sub='refresh_cache'):
    return f'{out_root}/{sub}/s{seed}.pkl.gz'


def job(kind, r, seed, out_root=OUT, group=None, run_group=None, old_group='old',
        cache_sub='refresh_cache', load_cache=False, est=None, prio=1, **kw):
    """kind 'old' hoặc 'full'. group: thư mục kết quả (và tiền tố id); run_group: tên nhóm để
    chọn bằng --groups (mặc định bằng group). load_cache: job cần file bộ đệm có sẵn."""
    group = group or kind
    j = D1.avail(r, seed, out_root=out_root, group=group, est=est or EST['old'], prio=prio, **kw)
    j['env']['RECORD_KILLS'] = '1'
    if kind == 'full':
        old_out = f'{out_root}/{old_group}/kbucket_r{r}_s{seed}.json'
        cache = cache_path(seed, out_root, cache_sub)
        j['env'].update({'JOIN_REFRESH': '1', 'KILL_FROM': old_out, 'REFRESH_CACHE': cache})
        j['needs'] = j['needs'] + [old_out] + ([cache] if load_cache else [])
    j['group'] = run_group or group
    j['kind'] = f'avail_{kind}'
    return j


def build(groups=None):
    J = []
    want = (lambda g: True) if not groups else (lambda g: g in groups)
    for s in SEEDS:
        for r in (1, 2, 3):
            if want('old'):
                J.append(job('old', r, s))
            if r == 1 and want('full_a'):
                J.append(job('full', r, s, run_group='full_a', est=EST['full_a']))
            if r > 1 and want('full_b'):
                J.append(job('full', r, s, run_group='full_b', load_cache=True, est=EST['full_b']))
    if want('chk'):
        J.append(job('full', 1, SEEDS[0], group='chk', load_cache=True, est=EST['full_b'], prio=0))
    if want('sm'):
        s = SEEDS[0]
        small = dict(steps='0,0.30', nodes=800, files=1500, sample=10)
        J.append(job('old', 2, s, group='sm_old', **small))
        J.append(job('full', 2, s, group='sm_full', old_group='sm_old', cache_sub='sm_cache', **small))
        J.append(job('full', 2, s, group='sm_full_c', old_group='sm_old', cache_sub='sm_cache',
                     load_cache=True, **small))
    return J


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--groups', default='', help='old, full_a, full_b, chk, sm (cách nhau bởi dấu phẩy)')
    ap.add_argument('--write', required=True)
    a = ap.parse_args()
    jobs = build(set(a.groups.split(',')) if a.groups else None)
    os.makedirs(os.path.dirname(a.write) or '.', exist_ok=True)
    with open(a.write, 'w', encoding='utf-8') as fh:
        for j in jobs:
            fh.write(json.dumps(j, ensure_ascii=False) + '\n')
    print(f'{len(jobs)} job -> {a.write}')
