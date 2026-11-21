"""Dựng artifact VortexHash (VHash của Semord) cho code và SciFact, mỗi seed một model.

Cấu hình VHash lấy từ bộ chọn của tác giả (vortex_model_selector, vai trò "best"), chạy trên
query validation với overlay 1.000 node; mặc định dùng cấu hình đã cố định trong sel/*.json (xem
semord_pipeline.sh). Mỗi seed huấn luyện lại model với đúng cấu hình đó (--seed khác nhau), rồi đặt
vào Vortex_system/methods/vortex_v1_<ds>_s<seed>/ để vortex_bench nhận ra khi configure; cấu hình
dùng để huấn luyện ghi trong semord_config.json của thư mục đó.

Dùng: python3 semord_artifacts.py --lh <LearnedHash> --vx <Vortex_system> --data <semord_data>
      --sel-dir <thư mục chứa *_sel.json và *.hnsw.index> [--seeds 20235956,1,...]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def run(cmd, env=None):
    print('+', ' '.join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-2000:] + r.stderr[-4000:])
        raise SystemExit(f'lệnh lỗi ({r.returncode}): {cmd[0]}')
    return r.stdout


def train_args(cfg):
    a = ['--K', cfg['K'], '--hash_bits', 64, '--centroid_knn', cfg['centroid_knn'],
         '--cdf_models', cfg['cdf_models'], '--cdf_branch', cfg['cdf_branch']]
    if cfg.get('enable_2opt'):
        a += ['--enable_2opt', '--two_opt_iters', cfg.get('two_opt_iters', 1)]
    else:
        a += ['--disable_2opt']
    if not cfg.get('graph_centroid_order', True):
        a += ['--disable_graph_centroid_order']
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lh', required=True)
    ap.add_argument('--vx', required=True)
    ap.add_argument('--data', required=True)
    ap.add_argument('--sel-dir', required=True)
    ap.add_argument('--datasets', default='code,scifact')
    ap.add_argument('--seeds', default=','.join(str(s) for s in SEEDS))
    ap.add_argument('--threads', default='2')
    a = ap.parse_args()
    cli = os.path.join(a.lh, 'build', 'hash_functions_core', 'Vortex', 'vortex_v1_cli')
    env = dict(os.environ, VORTEX_ROOT=os.path.abspath(a.lh))
    seeds = [int(s) for s in a.seeds.split(',') if s]
    summary = {}
    for ds in a.datasets.split(','):
        sel = json.load(open(os.path.join(a.sel_dir, f'{ds}_sel.json')))
        cfg = sel['best']['config']
        ts = int(cfg['target_skeleton'])
        nsw = os.path.join(a.sel_dir, f'{ds}_nsw_ts{ts}.csr')
        if not os.path.exists(nsw):
            run([cli, 'extract_nsw', '--index', os.path.join(a.sel_dir, f'{ds}.hnsw.index'),
                 '--target_skeleton', ts, '--output', nsw])
        base = os.path.join(a.data, ds, f'{ds}_base.fvecs')
        for s in seeds:
            name = f'{ds}_s{s}'
            out = os.path.join(a.vx, 'methods', f'vortex_v1_{name}')
            # model đã có chỉ giữ lại khi huấn luyện đúng cấu hình hiện tại (ghi trong semord_config.json)
            if os.path.exists(os.path.join(out, 'vortex.json')):
                try:
                    same = json.load(open(os.path.join(out, 'semord_config.json'))) == cfg
                except (OSError, ValueError):
                    same = False
                if same:
                    continue
                print(f'{name}: model có sẵn không cùng cấu hình VHash hiện tại, huấn luyện lại', flush=True)
                shutil.rmtree(out)
            tmp = out + '.tmp'
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            run([cli, 'train', '--dataset', base, '--nsw', nsw] + train_args(cfg) +
                ['--seed', s, '--threads', a.threads, '--output', os.path.join(tmp, 'model.bin'),
                 '--codegen', '--codegen-dir', tmp, '--codegen-name', f'semord_{name}'], env=env)
            json.dump(cfg, open(os.path.join(tmp, 'semord_config.json'), 'w'), indent=1)
            os.replace(tmp, out)
        summary[ds] = {'config': cfg, 'selector_query': sel.get('query'),
                       'selector_seed': sel.get('seed'), 'nsw': os.path.basename(nsw)}
    json.dump(summary, open(os.path.join(a.sel_dir, 'artifact_configs.json'), 'w'), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
