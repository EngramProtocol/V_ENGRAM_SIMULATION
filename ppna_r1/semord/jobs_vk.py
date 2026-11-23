"""Job V-Engram cho phép so với Semord: mô hình iterative, join đầy đủ (một vòng làm mới k-bucket),
T = 8; code và SciFact, 10 seed. Mặc định N = 1.000 với K = 2 (= N/500, cùng tỉ lệ N/K với cấu hình
chính), thêm K = 4 và 10; ở N = 2.000 dùng --nodes 2000 --k 4 --extra-k 2,10. Cùng định dạng job và
bộ chạy ppna_r1/dot1/runner.py.

--l8: điểm vận hành L = 8 (kế hoạch lt của iterative.py, biến thể L8_T5 và L8_T8 trên cùng một
mạng) ở K = --k, nhóm vk<N>_L8; dùng cho run_semord_l8.sh."""
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


def build(nodes=1000, k=2, extra_k='4,10', l8=False):
    J = []
    for s in D3.SEEDS:
        for ds in ('code', 'scifact'):
            if l8:
                J.append(D3.it(f'vk{nodes}_L8', ds, 'lt', ds, s, nodes=nodes, est=250 * nodes // 1000,
                               out_root=OUT, args=['--num-tables', '8', '--k', str(k), '--join-refresh', '1']))
            else:
                J.append(D3.it(f'vk{nodes}', ds, 'ws', ds, s, nodes=nodes, est=200 * nodes // 1000, out_root=OUT,
                               args=['--k', str(k), '--extra-k', extra_k, '--join-refresh', '1']))
    return J


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', required=True)
    ap.add_argument('--nodes', type=int, default=1000)
    ap.add_argument('--k', type=int, default=2)
    ap.add_argument('--extra-k', default='4,10')
    ap.add_argument('--l8', action='store_true', help='điểm vận hành L = 8 (T = 5 và 8) ở K = --k')
    a = ap.parse_args()
    J = build(a.nodes, a.k, a.extra_k, a.l8)
    with open(a.write, 'w', encoding='utf-8') as fh:
        for j in J:
            fh.write(json.dumps(j, ensure_ascii=False) + '\n')
    print(f'{len(J)} job V-Engram N = {a.nodes}')
