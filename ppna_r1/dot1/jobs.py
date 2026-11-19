"""Danh sách job của đợt 1 (ppna-r1-dot1). Mỗi job là một dict:

    id      tên duy nhất, cũng là đường dẫn tương đối của file kết quả (không đuôi)
    group   nhóm thí nghiệm (xem GROUPS)
    kind    v2 | lsh | avail | churn | coll
    cmd     lệnh (list), chạy từ gốc repo
    env     biến môi trường thêm vào
    out     file kết quả
    needs   file dữ liệu phải có; thiếu thì job bị bỏ qua và báo ở cuối
    prio    1 = sinh lại số của bản đã nộp, 2 = thí nghiệm mới cho nhận xét
    est     thời gian ước (giây) trên một nhân, đo trên máy thử; chỉ để sắp thứ tự và ước ETA
    big     True với overlay >= 35.000 peer (giới hạn số job lớn chạy cùng lúc)

Mọi job dùng cùng 10 seed. Cấu hình chính: N = 10.000, L = 5, T = 8, K = 20,
r = 1, c = 16, PQ m = 512, kappa = 30, 500 query, phép chiếu Achlioptas chuẩn hoá cột.
Mỗi nhóm chỉ đổi đúng trục nó quét.
"""
import os

SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
OUT = 'ppna_r1/out_dot1'
PY = os.environ.get('PY', 'python3')
MODES = ['semantic', 'random_unique', 'random_keys', 'random_slots', 'random_equalcand']
LOSS_LEVELS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
AVAIL_STEPS = '0,0.05,0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.45,0.50'
LSH_WIDTHS = '8,9,10,11,12,13,14,15,16'
# (corpus, N): hai đối tượng mỗi peer
SCALES = [('code30k', 15000), ('code40k', 20000), ('code50k', 25000),
          ('code70k', 35000), ('code100k', 50000)]
# (tên, dataset, biến thể PQ) cho R1-4
WORKLOADS = [('squad', 'squad', 'm512'), ('code_e5', 'code_e5', 'm512'),
             ('scifact_e5', 'scifact_e5', 'm512'), ('code_jina', 'code_jina', 'm448')]
# Bảng 10: (r, chu kỳ sửa phút). 480 = 4 lần median session 120 phút; 1320 = 22 giờ.
CHURN_CONFIGS = [(1, 0), (1, 480), (4, 1320)]

# File do bước e5 và jina của ppna-r1-prep sinh ra (hai bước nhúng lâu nhất). Job chỉ thiếu
# các file này được coi là "chờ dữ liệu": smoke test và runner không báo lỗi vì chúng, và
# lần chạy run_dot1.sh sau khi bước chuẩn bị xong sẽ chạy đúng các job đó.
DEFERRED_DATA = ('data/code_e5_', 'data/scifact_e5_', 'data/code_jina_')


def missing_inputs(job):
    return [p for p in job['needs'] if not os.path.exists(p)]


def waits_for_prep(job, missing=None):
    m = missing_inputs(job) if missing is None else missing
    return bool(m) and all(p.startswith(DEFERRED_DATA) for p in m)


GROUPS = {
    't4':    'Bảng 4: semantic và bốn control, hai corpus (kèm thống kê từng bảng chiếu)',
    't5':    'Bảng 5: T thuộc {1,3,5,12} với K = 20; K thuộc {10,40,80} với T = 8',
    't8':    'Bảng 8: r thuộc {2,4,5,10}, semantic và random nominal',
    'loss':  'Bảng 9 và hình: Final R@5 khi mất 5..50% peer, r = 1, 2; r = 3 ở 30%',
    'avail': 'Bảng 9 và hình: availability k-bucket, r = 1, 2, 3, mất 0..50% peer',
    'regress': 'Hồi quy: availability seed 20235956 đúng lệnh đợt kiểm 17/11, phải trùng từng số',
    'churn': 'Bảng 10: churn, ba cấu hình',
    'kappa': 'Mục 4.1: kappa thuộc {10,50,100}',
    'val':   'R1-5: V-Engram trên query validation (để chọn b_LSH)',
    'lsh':   'Bảng 6: Bucket-LSH quét b = 8..16, T thuộc {1,4,8}, validation và test',
    'ws':    'Bảng 11, 12, hình 4: weak scaling 15k..50k peer, K = 20 và K = N/500',
    'r11':   'R1-1: họ phép chiếu, PQ, L, c',
    'r14':   'R1-4: SQuAD, e5-large-v2, jina-code-embeddings-0.5b',
    'trunc': 'R1-5, R1-7: khoá cụt b bit ở 10k, 25k, 50k peer',
    'coll':  'R1-1: tỉ lệ trùng bit theo góc so với 1 - theta/pi',
}


def _data(ds, pq):
    D = f'data/{ds}'
    f = [f'{D}_corpus_embeddings.npy', f'{D}_query_embeddings.npy', f'{D}_ground_truth.json']
    if pq not in ('nopq',):
        sfx = '' if pq == 'm256' else f'_{pq}'
        f += [f'{D}_pq_codes{sfx}.npy', f'{D}_pq_codebook{sfx}.npy']
    return f


def v2(group, name, ds, seed, nodes=10000, L=5, T=8, K=20, r=1, c=16, pq='m512',
       mode='semantic', qs='test', key_bits=63, family=None, loss=0.0, kappa=30,
       per_table=False, prio=1, est=45, nq=500, out_root=OUT):
    out = f'{out_root}/{group}/{name}_s{seed}.json'
    cmd = [PY, 'main_simulation_v2.py', '--dataset', ds, '--nodes', str(nodes),
           '--nq', str(nq), '--num-tables', str(L), '--k-query', str(K),
           '--meta-anchors', str(r), '--multi-probe', str(T), '--probe-bits', str(c),
           '--seed', str(seed), '--routing', mode]
    if pq == 'nopq':
        cmd += ['--no-pq']
    elif pq == 'm256':
        cmd += ['--use-pq']
    else:
        cmd += ['--use-pq', '--pq-variant', pq]
    if qs != 'test':
        cmd += ['--query-set', qs]
    if key_bits != 63:
        cmd += ['--key-bits', str(key_bits)]
    if family:
        cmd += ['--proj-family', family]
    if loss > 0:
        cmd += ['--node-loss', f'{loss:.2f}']
    if kappa != 30:
        cmd += ['--local-topk', str(kappa)]
    if per_table:
        cmd += ['--per-table-stats']
    cmd += ['--out', out]
    needs = _data(ds, pq)
    if qs == 'val':
        needs = [n for n in needs if 'query_embeddings' not in n and 'ground_truth' not in n]
        needs += [f'data/{ds}_val_query_embeddings.npy', f'data/{ds}_val_ground_truth.json']
    return {'id': f'{group}/{name}_s{seed}', 'group': group, 'kind': 'v2', 'cmd': cmd,
            'env': {'NORMALIZE_ROWS': '1'}, 'out': out, 'needs': needs, 'prio': prio,
            'est': est, 'big': nodes >= 35000, 'timeout': 4 * 3600 if nodes >= 25000 else 3600,
            'seed': seed}


def lsh(ds, T, qs, seed, prio=1, est=120, widths=LSH_WIDTHS, out_root=OUT, group='lsh'):
    out = f'{out_root}/{group}/{ds}_T{T}_{qs}_s{seed}.json'
    qsfx = '_val' if qs == 'val' else ''
    env = {'CORPUS': ds, 'PQ_VARIANT': 'm512', 'QUERY_SET': qs, 'BUCKET_ONLY': '1',
           'BUCKET_PROBES': str(T), 'BUCKET_WIDTHS': widths, 'LSH_SEED': str(seed),
           'RNG_SEED': str(seed), 'OUT_JSON': out, 'NORMALIZE_ROWS': '1'}
    needs = [f'data/{ds}_corpus_embeddings.npy', f'data/{ds}{qsfx}_query_embeddings.npy',
             f'data/{ds}{qsfx}_ground_truth.json', f'data/{ds}_pq_codes_m512.npy',
             f'data/{ds}_pq_codebook_m512.npy']
    return {'id': f'{group}/{ds}_T{T}_{qs}_s{seed}', 'group': group, 'kind': 'lsh',
            'cmd': [PY, 'baselines.py'], 'env': env, 'out': out, 'needs': needs,
            'prio': prio, 'est': est, 'big': False, 'timeout': 2 * 3600, 'seed': seed}


def avail(r, seed, steps=AVAIL_STEPS, nodes=10000, files=20000, sample=500, prio=1,
          est=600, out_root=OUT, group='avail', name=None):
    name = name or f'kbucket_r{r}'
    out = f'{out_root}/{group}/{name}_s{seed}.json'
    env = {'DATASET': 'code', 'NUM_NODES': str(nodes), 'NUM_FILES': str(files),
           'RECOVERY_SAMPLE': str(sample), 'CHURN_STEPS': steps, 'META_ANCHORS': str(r),
           'NET_SEED': str(seed), 'SAMPLE_SEED': str(seed), 'INGEST_SAMPLE_ONLY': '1',
           'PQ_VARIANT': 'm512', 'ROUTING_TABLE': 'kbucket', 'BOOTSTRAP': 'join',
           'OUT_JSON': out, 'NORMALIZE_ROWS': '1'}
    return {'id': f'{group}/{name}_s{seed}', 'group': group, 'kind': 'avail',
            'cmd': [PY, '-u', 'main_churn_test.py'], 'env': env, 'out': out,
            'needs': _data('code', 'm512'), 'prio': prio, 'est': est, 'big': False,
            'timeout': 6 * 3600, 'seed': seed}


def churn(r, rep, seed, nodes=10000, nq=200, ses=120, duration=None, ds='code', prio=1,
          out_root=OUT, group='churn'):
    # như run_churn.sh và run_remaining_vong2.sh: thời lượng = max(6 median, 3 chu kỳ sửa)
    dur = duration if duration is not None else max(6 * ses, 3 * rep)
    out = f'{out_root}/{group}/r{r}_rep{rep}_s{seed}.json'
    cmd = [PY, 'main_churn_engine.py', '--dataset', ds, '--nodes', str(nodes), '--nq', str(nq),
           '--median-session', str(ses), '--duration', str(dur), '--session-dist', 'weibull',
           '--meta-anchors', str(r), '--repair-interval', str(rep), '--seed', str(seed),
           '--out', out]
    est = {0: 40, 480: 100}.get(rep, 150) * (2 if r > 1 else 1)
    return {'id': f'{group}/r{r}_rep{rep}_s{seed}', 'group': group, 'kind': 'churn',
            'cmd': cmd, 'env': {'NORMALIZE_ROWS': '1'}, 'out': out,
            'needs': _data(ds, 'm512'), 'prio': prio, 'est': est, 'big': False,
            'timeout': 16 * 3600, 'seed': seed}


def coll(ds, seeds, prio=2, out_root=OUT, group='coll', pairs_random=20):
    out = f'{out_root}/{group}/{ds}.json'
    cmd = [PY, 'ppna_r1/dot1/bit_collision.py', '--dataset', ds,
           '--seeds', ','.join(str(s) for s in seeds), '--random-per-query', str(pairs_random),
           '--out', out]
    return {'id': f'{group}/{ds}', 'group': group, 'kind': 'coll', 'cmd': cmd,
            'env': {'NORMALIZE_ROWS': '1'}, 'out': out,
            'needs': [f'data/{ds}_corpus_embeddings.npy', f'data/{ds}_query_embeddings.npy',
                      f'data/{ds}_ground_truth.json'],
            'prio': prio, 'est': 300, 'big': False, 'timeout': 3600, 'seed': None}


def build(seeds=None, groups=None):
    seeds = seeds or SEEDS
    J = []

    def want(g):
        return groups is None or g in groups

    for s in seeds:
        # ---- Bảng 4 (kèm Bảng 12 và thống kê từng bảng chiếu ở hàng semantic)
        if want('t4'):
            for ds in ('code', 'scifact'):
                for m in MODES:
                    J.append(v2('t4', f'{ds}_{m}', ds, s, mode=m, per_table=(m == 'semantic'),
                                est=70 if m == 'random_equalcand' else 45))
        # ---- Bảng 5
        if want('t5'):
            for T in (1, 3, 5, 12):
                J.append(v2('t5', f'code_T{T}_K20', 'code', s, T=T, est=30 + 4 * T))
            for K in (10, 40, 80):
                J.append(v2('t5', f'code_T8_K{K}', 'code', s, K=K, est=30 + K))
        # ---- Bảng 8
        if want('t8'):
            for r in (2, 4, 5, 10):
                for m in ('semantic', 'random_slots'):
                    J.append(v2('t8', f'code_r{r}_{m}', 'code', s, r=r, mode=m, est=40 + 3 * r))
        # ---- Bảng 9: Final R@5 theo mức mất peer (r = 1 mất 0% là Bảng 4; r = 2 mất 0% là Bảng 8)
        if want('loss'):
            for r in (1, 2):
                for f in LOSS_LEVELS:
                    J.append(v2('loss', f'code_r{r}_loss{f:.2f}', 'code', s, r=r, loss=f, est=40))
            J.append(v2('loss', 'code_r3_loss0.30', 'code', s, r=3, loss=0.30, est=40))
            J.append(v2('loss', 'code_r3_loss0.00', 'code', s, r=3, est=40))
        # ---- Bảng 9: availability trên k-bucket, một lần chạy cho mọi mức mất peer
        if want('avail'):
            for r in (1, 2, 3):
                J.append(avail(r, s))
        # ---- hồi quy: đúng lệnh của đợt kiểm 17/11 (out_verify_s2/D), phải trùng từng số
        if want('regress') and s == SEEDS[0]:
            for r in (1, 2, 3):
                J.append(avail(r, s, steps='0,0.10,0.20,0.30', group='regress',
                               name=f'avail_kbucket_r{r}', est=300))
        # ---- Bảng 10
        if want('churn'):
            for r, rep in CHURN_CONFIGS:
                J.append(churn(r, rep, s))
        # ---- kappa
        if want('kappa'):
            for ds in ('code', 'scifact'):
                for kp in (10, 50, 100):
                    J.append(v2('kappa', f'{ds}_kappa{kp}', ds, s, kappa=kp, est=45))
        # ---- R1-5: V-Engram trên validation, Bucket-LSH trên validation và test
        if want('val'):
            for ds in ('code', 'scifact'):
                J.append(v2('val', f'{ds}_semantic', ds, s, qs='val', est=45))
        if want('lsh'):
            for ds in ('code', 'scifact'):
                for T in (1, 4, 8):
                    for qs in ('val', 'test'):
                        J.append(lsh(ds, T, qs, s, est=60 + 15 * T))
        # ---- weak scaling (10k là Bảng 4); control random nominal chỉ ở 25k và 50k
        if want('ws'):
            for ds, N in SCALES:
                p = 1 if N in (25000, 50000) else 2
                for K in (20, N // 500):
                    for m in ('semantic', 'random_slots'):
                        if m == 'random_slots' and N not in (25000, 50000):
                            continue
                        J.append(v2('ws', f'{ds}_N{N}_K{K}_{m}', ds, s, nodes=N, K=K, mode=m,
                                    prio=p if m == 'semantic' else 2, est=int(35 * (N / 10000) ** 1.1)))
        # ---- R1-1 (cả hai corpus, mỗi điểm kèm control random equal peers)
        if want('r11'):
            sweeps = [('gauss', dict(family='gaussian'))]
            sweeps += [(f'pq_{v}', dict(pq=v)) for v in ('m64', 'm128', 'm256', 'nopq')]
            sweeps += [(f'L{L}', dict(L=L)) for L in (3, 4, 6, 8, 10)]
            sweeps += [('L8_T5', dict(L=8, T=5))]
            sweeps += [(f'c{c}', dict(c=c)) for c in (8, 9, 12, 24)]
            sweeps += [('c9_T5', dict(c=9, T=5)), ('c12_T6', dict(c=12, T=6))]
            for ds in ('code', 'scifact'):
                for lab, kw in sweeps:
                    for m in ('semantic', 'random_unique'):
                        est = 45 + (6 * kw.get('L', 5) if 'L' in kw else 0)
                        J.append(v2('r11', f'{ds}_{lab}_{m}', ds, s, mode=m, prio=2, est=est, **kw))
        # ---- R1-4
        if want('r14'):
            for lab, ds, pq in WORKLOADS:
                for m in MODES:
                    J.append(v2('r14', f'{lab}_{m}', ds, s, pq=pq, mode=m, prio=2,
                                est=70 if m == 'random_equalcand' else 45))
        # ---- khoá cụt (b = 63 là cấu hình chính và weak scaling K = 20)
        if want('trunc'):
            for ds, N in (('code', 10000), ('code50k', 25000), ('code100k', 50000)):
                for b in (8, 10, 12, 16):
                    J.append(v2('trunc', f'{ds}_N{N}_b{b}', ds, s, nodes=N, key_bits=b, prio=2,
                                est=int(35 * (N / 10000) ** 1.1)))
    # ---- R1-1: tỉ lệ trùng bit theo góc, mọi seed trong một job
    if want('coll'):
        for ds in ('code', 'scifact'):
            J.append(coll(ds, seeds))
    ids = [j['id'] for j in J]
    assert len(ids) == len(set(ids)), 'trùng id job'
    return J


def build_smoke(root='ppna_r1/logs_dot1/smoke'):
    """Bản thu nhỏ của mọi kiểu job, chạy vài phút. Kiểm cờ mới và đường dữ liệu mới."""
    s = 1
    o = f'{root}/out'
    J = [
        v2('sm', 'v2_semantic_pertable', 'scifact', s, nodes=2000, nq=5, per_table=True, out_root=o),
        v2('sm', 'v2_randcand', 'scifact', s, nodes=2000, nq=5, mode='random_equalcand', out_root=o),
        v2('sm', 'v2_gauss_L8_T5', 'scifact', s, nodes=2000, nq=5, family='gaussian', L=8, T=5,
           out_root=o),
        v2('sm', 'v2_keybits10', 'scifact', s, nodes=2000, nq=5, key_bits=10, out_root=o),
        v2('sm', 'v2_c24_loss', 'scifact', s, nodes=2000, nq=5, c=24, loss=0.3, r=2, out_root=o),
        v2('sm', 'v2_nopq_kappa10', 'scifact', s, nodes=2000, nq=5, pq='nopq', kappa=10, out_root=o),
        v2('sm', 'v2_m256', 'scifact', s, nodes=2000, nq=5, pq='m256', out_root=o),
        v2('sm', 'v2_m64', 'scifact', s, nodes=2000, nq=5, pq='m64', out_root=o),
        v2('sm', 'v2_m128', 'code', s, nodes=2000, nq=5, pq='m128', out_root=o),
        v2('sm', 'v2_val', 'code', s, nodes=2000, nq=5, qs='val', out_root=o),
        v2('sm', 'v2_squad', 'squad', s, nodes=2000, nq=5, out_root=o),
        v2('sm', 'v2_code_e5', 'code_e5', s, nodes=2000, nq=5, out_root=o),
        v2('sm', 'v2_scifact_e5', 'scifact_e5', s, nodes=2000, nq=5, out_root=o),
        v2('sm', 'v2_code_jina', 'code_jina', s, nodes=2000, nq=5, pq='m448', out_root=o),
        v2('sm', 'v2_code30k', 'code30k', s, nodes=15000, nq=5, K=30, out_root=o),
        v2('sm', 'v2_code40k', 'code40k', s, nodes=2000, nq=5, out_root=o),
        v2('sm', 'v2_code70k', 'code70k', s, nodes=2000, nq=5, out_root=o),
        v2('sm', 'v2_code100k_b8', 'code100k', s, nodes=2000, nq=5, key_bits=8, out_root=o),
        lsh('scifact', 4, 'val', s, widths='10,12', out_root=o, group='sm'),
        lsh('code', 8, 'test', s, widths='12', out_root=o, group='sm'),
        avail(2, s, steps='0,0.30', nodes=800, files=1500, sample=10, out_root=o, group='sm'),
        churn(1, 120, s, nodes=1000, nq=5, duration=360, ds='scifact', out_root=o, group='sm'),
        coll('scifact', [1], out_root=o, group='sm', pairs_random=2),
    ]
    for j in J:
        j['prio'], j['big'] = 0, False
        j['timeout'] = 1800
    return J


if __name__ == '__main__':
    import argparse
    import collections
    import json
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
