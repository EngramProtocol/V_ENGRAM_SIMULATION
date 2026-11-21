"""Job V-Engram ở N = 1.000 peer cho phép so với Semord: mô hình iterative, join đầy đủ (một vòng làm
mới k-bucket), T = 8, K = 2 (= N/500, cùng tỉ lệ N/K với cấu hình chính), 4 và 10; code và SciFact,
10 seed. Cùng định dạng job và bộ chạy ppna_r1/dot1/runner.py."""
import importlib.util
import json
import os

OUT = 'ppna_r1/out_semord'


def _load(name, rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', rel)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D3 = _load('dot3_jobs', 'dot3/jobs.py')


def build():
    J = []
    for s in D3.SEEDS:
        for ds in ('code', 'scifact'):
            J.append(D3.it('vk1000', ds, 'ws', ds, s, nodes=1000, est=200, out_root=OUT,
                           args=['--k', '2', '--extra-k', '4,10', '--join-refresh', '1']))
    return J


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', required=True)
    a = ap.parse_args()
    J = build()
    with open(a.write, 'w', encoding='utf-8') as fh:
        for j in J:
            fh.write(json.dumps(j, ensure_ascii=False) + '\n')
    print(f'{len(J)} job V-Engram N = 1.000')
