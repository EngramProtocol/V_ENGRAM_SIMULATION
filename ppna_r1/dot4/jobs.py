"""Danh sách job của đợt 4 (ppna-r1-dot4): L = 8 bảng trên mô hình iterative, cho mục chọn điểm
vận hành (R2-2). Cùng định dạng job và cùng bộ chạy ppna_r1/dot1/runner.py.

- lt: iterative, join đầy đủ (join cũ cộng một vòng làm mới k-bucket), L = 8, biến thể T = 8 và
  T = 5 (cùng 40 target với cấu hình chính) trên cùng một mạng.
- lt_old: như lt nhưng join cũ, để có số cho phân tích độ nhạy theo join như mọi bảng iterative khác.
- r11_L8: mô hình lý tưởng, chạy lại đúng hai job L8 và L8_T5 của nhóm r11 đợt 1 (cùng lệnh, cùng
  seed), để ghép cặp iterative với lý tưởng theo seed và kiểm hồi quy với đợt 1.

Các tham số khác như cấu hình chính: N = 10.000, K = 20, r = 1, c = 16, PQ m = 512, kappa = 30,
500 query, Ripple Search stable/all, R_max = 15. Cùng 10 seed, code và SciFact.
"""
import importlib.util
import json
import os

OUT = 'ppna_r1/out_dot4'

GROUPS = {
    'lt': 'iterative, join đầy đủ, L = 8, T = 8 và T = 5',
    'lt_old': 'iterative, join cũ, L = 8, T = 8 và T = 5',
    'r11_L8': 'mô hình lý tưởng, L = 8 và L = 8 với T = 5 (chạy lại job của đợt 1)',
}


def _load(name, rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', rel)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D1 = _load('dot1_jobs', 'dot1/jobs.py')
D3 = _load('dot3_jobs', 'dot3/jobs.py')
SEEDS = D3.SEEDS
L8 = ['--num-tables', '8']


def build():
    J = []
    for s in SEEDS:
        for ds in ('code', 'scifact'):
            big = ds == 'code'
            J.append(D3.it('lt', ds, 'lt', ds, s, out_root=OUT, prio=1, est=1300 if big else 700,
                           args=L8 + D3.JR))
            J.append(D3.it('lt_old', ds, 'lt', ds, s, out_root=OUT, prio=2, est=1500 if big else 800,
                           args=L8))
            for lab, kw in (('L8', dict(L=8)), ('L8_T5', dict(L=8, T=5))):
                J.append(D1.v2('r11_L8', f'{ds}_{lab}_semantic', ds, s, mode='semantic', prio=0,
                               est=93, out_root=OUT, **kw))
    ids = [j['id'] for j in J]
    assert len(ids) == len(set(ids)), 'trùng id job'
    return J


def build_smoke(root='ppna_r1/logs_dot4/smoke'):
    """Bản thu nhỏ của mọi kiểu job (2.000 peer, 4.000 object, 10 query)."""
    s = 1
    o = f'{root}/out'
    small = dict(nodes=2000, nq=10, num_files=4000, out_root=o, prio=0)
    J = [D3.it('sm', 'lt_code', 'lt', 'code', s, args=L8 + D3.JR, **small),
         D3.it('sm', 'lt_old_scifact', 'lt', 'scifact', s, args=L8, **small),
         D1.v2('sm', 'v2_L8_T5', 'scifact', s, nodes=2000, nq=5, L=8, T=5, out_root=o, prio=0)]
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
        print(f'{g:7s} {cnt[g]:4d} job  ~{est[g] / 3600:5.1f} giờ một nhân  {GROUPS.get(g, "")}')
    print(f'TỔNG    {len(J):4d} job  ~{sum(est.values()) / 3600:5.1f} giờ một nhân')
