"""Aggregation of batch dot7: bits per PQ index at m = 512 under the reference model.

    python3 ppna_r1/dot7/aggregate.py [--root ppna_r1/out_dot7] [--ref ppna_r1/out_dot1]
        [--out ppna_r1/dot7_summary.json] > ppna_r1/dot7_report.txt

1. Codebooks: centroids, packed code and record size, codebook size, reconstruction error, and the
   checks of the data step p5 (out_dot7/pq_bits.json).
2. Regression: q = 8 repeats the command of dot1 group t4 (semantic), so every value must equal the
   file of dot1 (--ref), when present.
3. Routing and placement do not read the PQ codes, so reachable Recall@5, evaluated peers, record
   load, and RPC counts must be identical for every q at one seed.
4. Final Recall@5: mean +- SD over seeds and the paired difference from q = 8 with a 95% confidence
   interval (t, n - 1 degrees of freedom).
5. From dot1 group r11, paired by seed: m = 512 with q = 4 against m = 256 with q = 8 (both
   256-byte codes), and exact cosine ranking (no PQ) against every q.
"""
import argparse
import json
import math
import os
import statistics as st

T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
        10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 19: 2.093, 29: 2.045}
SEEDS = [20235956, 1, 2, 3, 4, 5, 6, 7, 8, 9]
CORPORA = ('code', 'scifact')
NAME = {'code': 'CodeSearchNet', 'scifact': 'SciFact'}
BITS = (8, 6, 4)
ROUTING = ['reachable_recall5', 'reachable_hit5', 'mean_nodes_touched', 'pct_network_touched',
           'A_distinct_anchors', 'metadata_gini', 'metadata_max', 'rpc_mean', 'rpc_max',
           'work_mean', 'work_max', 'p_each', 'or_observed']
# fields that must equal dot1 exactly; the other fields (correlation summaries, the mean number of
# unique candidates) may differ slightly between numpy builds and are reported with their largest
# difference
EXACT = ROUTING + ['recall5', 'recall10', 'returned_recall5', 'final_hit5', 'returned_hit5']
PROBLEMS = []


def load(path):
    """Result file, or None when it or its .ok marker is missing."""
    if not (os.path.isfile(path) and os.path.isfile(path + '.ok')):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def summ(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {'n': len(xs), 'mean': st.mean(xs), 'sd': st.stdev(xs) if len(xs) > 1 else 0.0}


def paired(a, b):
    d = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    if len(d) < 2:
        return None
    m, sd = st.mean(d), st.stdev(d)
    h = T975.get(len(d) - 1, 1.96) * sd / math.sqrt(len(d))
    return {'n': len(d), 'mean': m, 'lo': m - h, 'hi': m + h, 'sd': sd,
            'neg': sum(1 for x in d if x < 0), 'pos': sum(1 for x in d if x > 0)}


def fs(s, nd=2):
    return '—' if s is None else f'{s["mean"]:.{nd}f} ± {s["sd"]:.{nd}f}' + (
        '' if s['n'] == len(SEEDS) else f' [{s["n"]}/{len(SEEDS)}]')


def fp(p, nd=2):
    if p is None:
        return '—'
    return (f'{p["mean"]:+.{nd}f} [{p["lo"]:+.{nd}f}, {p["hi"]:+.{nd}f}] '
            f'(below in {p["neg"]}/{p["n"]} seeds)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='ppna_r1/out_dot7')
    ap.add_argument('--ref', default='ppna_r1/out_dot1')
    ap.add_argument('--out', default='ppna_r1/dot7_summary.json')
    a = ap.parse_args()
    S = {'root': a.root, 'ref': a.ref}
    R = {(ds, q, s): load(os.path.join(a.root, 'pq', f'{ds}_q{q}_s{s}.json'))
         for ds in CORPORA for q in BITS for s in SEEDS}
    have = sum(v is not None for v in R.values())
    commits = sorted({v.get('commit', '') for v in R.values() if v is not None})
    print('BATCH 7 (ppna-r1-dot7): bits per PQ index at m = 512, reference model, '
          'principal configuration')
    print(f'results: {have}/{len(R)} runs with .ok | commit {", ".join(commits) or "—"} | '
          f'root {a.root}')
    if have < len(R):
        PROBLEMS.append(f'{len(R) - have} runs missing')

    # ---- 1. codebooks
    print('\n1. Codebooks (data step)')
    pb_path = os.path.join(a.root, 'pq_bits.json')
    pb = None
    if os.path.isfile(pb_path):
        with open(pb_path, encoding='utf-8') as fh:
            pb = json.load(fh)
        v = pb['versions']
        print(f'   {pb_path} | python {v["python"]}, numpy {v["numpy"]}, faiss {v["faiss"]}, '
              f'k-means seed {pb["seed"]}')
        print(f'   {"corpus":14s} {"q":>2s} {"centroids":>9s} {"code B":>7s} {"record B":>8s} '
              f'{"codebook B":>10s} {"MSE":>8s}  check')
        for ds in CORPORA:
            c = pb['corpora'].get(ds)
            if c is None:
                continue
            rows = [(8, c['q8_shipped'])] + [(q, c[f'q{q}']) for q in (6, 4)]
            for q, r in rows:
                if q == 8:
                    rt = c['q8_retrained']
                    chk = (f'shipped; retrained with the same routine: codebook '
                           f'{"identical" if rt["codebook_identical"] else "different"}, '
                           f'codes agree {rt["codes_agree_pct"]:.2f}%, MSE {rt["mse"]:.5f}')
                else:
                    eq = abs(r['mse_from_unpacked'] - r['mse']) <= 1e-9 * r['mse']
                    chk = (f'MSE of the unpacked indices {"equal" if eq else "differs"}, '
                           f'{r["not_nearest"]} not nearest, {r["argmin_differ"]} ties')
                print(f'   {NAME[ds]:14s} {q:2d} {r["centroids"]:9d} {r["code_bytes"]:7d} '
                      f'{r["record_bytes"]:8d} {r["codebook_bytes"]:10d} {r["mse"]:8.5f}  {chk}')
        PROBLEMS.extend(pb.get('problems', []))
        S['codebooks'] = pb['corpora']
    else:
        print(f'   {pb_path} missing')
        PROBLEMS.append('pq_bits.json missing')

    # ---- 2. regression with dot1
    print('\n2. Regression: q = 8 against dot1 group t4 (semantic), same command')
    same = total = 0
    noise = {}
    for ds in CORPORA:
        for s in SEEDS:
            d = R[(ds, 8, s)]
            ref = load(os.path.join(a.ref, 't4', f'{ds}_semantic_s{s}.json'))
            if d is None or ref is None:
                continue
            total += 1
            diff = sorted(k for k in set(d) | set(ref) if k != 'commit' and d.get(k) != ref.get(k))
            if not diff:
                same += 1
            for k in diff:
                x, y = d.get(k), ref.get(k)
                num = isinstance(x, (int, float)) and isinstance(y, (int, float))
                rel = abs(x - y) / max(abs(y), 1e-12) if num else float('inf')
                if k in EXACT or rel > 1e-5:
                    PROBLEMS.append(f'q = 8 differs from dot1 t4: {ds} seed {s}: {k} {x!r} vs {y!r}')
                else:
                    da, dr = noise.get(k, (0.0, 0.0))
                    noise[k] = (max(da, abs(x - y)), max(dr, rel))
    if not total:
        print(f'   no dot1 t4 results under {a.ref}, skipped')
    else:
        print(f'   {same}/{total} runs identical in every field except the commit')
        if noise:
            print('   the other runs differ only in fields outside the exact list (relative '
                  'difference at most 1e-5); largest absolute (relative) difference: '
                  + ', '.join(f'{k} {v[0]:.3g} ({v[1]:.1e})' for k, v in sorted(noise.items())))
    S['regression'] = {'identical': same, 'compared': total,
                       'other_differences': {k: {'abs': v[0], 'rel': v[1]}
                                             for k, v in sorted(noise.items())}}

    # ---- 3. routing does not read the codes
    print('\n3. Routing and placement identical for every q at one seed')
    inv = comp = 0
    for ds in CORPORA:
        for s in SEEDS:
            rs = [R[(ds, q, s)] for q in BITS]
            if any(x is None for x in rs):
                continue
            comp += 1
            bad = [k for k in ROUTING if len({json.dumps(x.get(k)) for x in rs}) > 1]
            if bad:
                PROBLEMS.append(f'routing differs across q: {ds} seed {s}: {", ".join(bad)}')
            else:
                inv += 1
    print(f'   {inv}/{comp} (corpus, seed) pairs identical in: {", ".join(ROUTING)}')
    S['routing_identical'] = {'identical': inv, 'compared': comp, 'fields': ROUTING}

    # ---- 4. recall
    print('\n4. Final Recall@5 by bits per index (m = 512), ten seeds; difference paired by seed')
    print(f'   {"corpus":14s} {"q":>2s} {"record B":>8s} {"Final R@5":>14s} '
          f'{"difference from q = 8 [95% CI]":>44s} {"returned R@5":>14s} {"R@10":>14s} '
          f'{"peers %":>8s} {"candidates":>10s}')
    S['recall'] = {}
    for ds in CORPORA:
        base = [None if R[(ds, 8, s)] is None else R[(ds, 8, s)]['recall5'] for s in SEEDS]
        for q in BITS:
            rs = [R[(ds, q, s)] for s in SEEDS]
            col = lambda k: [None if x is None else x[k] for x in rs]  # noqa: E731
            r5, ret, r10 = summ(col('recall5')), summ(col('returned_recall5')), summ(col('recall10'))
            peers, cand = summ(col('pct_network_touched')), summ(col('mean_unique_candidates'))
            p = None if q == 8 else paired(col('recall5'), base)
            rec = 168 + math.ceil(512 * q / 8)
            t_p = '—' if p is None else fp(p)
            t_peers = '—' if peers is None else '%.2f' % peers['mean']
            t_cand = '—' if cand is None else '%.0f' % cand['mean']
            print(f'   {NAME[ds]:14s} {q:2d} {rec:8d} {fs(r5):>14s} {t_p:>44s} '
                  f'{fs(ret):>14s} {fs(r10):>14s} {t_peers:>8s} {t_cand:>10s}')
            S['recall'][f'{ds}/q{q}'] = {'record_bytes': rec, 'recall5': r5, 'returned_recall5': ret,
                                         'recall10': r10, 'pct_network_touched': peers,
                                         'mean_unique_candidates': cand, 'diff_vs_q8': p,
                                         'per_seed': col('recall5')}
    runs = [d for d in R.values() if d is not None]
    full = sum(1 for d in runs if d['returned_recall5'] == d['reachable_recall5'])
    print(f'   returned Recall@5 equals reachable Recall@5 in {full}/{len(runs)} runs (every reachable '
          f'true neighbor is among the kappa candidates its peer returns)')
    S['returned_equals_reachable'] = {'runs': full, 'of': len(runs)}

    # ---- 5. comparisons with dot1 group r11
    print('\n5. From dot1 group r11, paired by seed')
    S['r11'] = {}
    for ds in CORPORA:
        m256 = [load(os.path.join(a.ref, 'r11', f'{ds}_pq_m256_semantic_s{s}.json')) for s in SEEDS]
        nopq = [load(os.path.join(a.ref, 'r11', f'{ds}_pq_nopq_semantic_s{s}.json')) for s in SEEDS]
        val = lambda xs: [None if x is None else x['recall5'] for x in xs]  # noqa: E731
        q4 = [None if R[(ds, 4, s)] is None else R[(ds, 4, s)]['recall5'] for s in SEEDS]
        if all(x is None for x in m256 + nopq):
            print(f'   {NAME[ds]}: no r11 results under {a.ref}, skipped')
            continue
        p_eq = paired(q4, val(m256))
        print(f'   {NAME[ds]:14s} m = 512, q = 4 minus m = 256, q = 8 (256-byte codes): '
              f'{fp(p_eq)} | m = 256: {fs(summ(val(m256)))}')
        S['r11'][f'{ds}/q4_minus_m256'] = p_eq
        S['r11'][f'{ds}/m256'] = summ(val(m256))
        S['r11'][f'{ds}/exact'] = summ(val(nopq))
        for q in BITS:
            vq = [None if R[(ds, q, s)] is None else R[(ds, q, s)]['recall5'] for s in SEEDS]
            p_ex = paired(val(nopq), vq)
            print(f'   {NAME[ds]:14s} exact cosine (no PQ) minus q = {q}: {fp(p_ex)}')
            S['r11'][f'{ds}/exact_minus_q{q}'] = p_ex

    print('\nPROBLEMS: none' if not PROBLEMS else f'\nPROBLEMS ({len(PROBLEMS)}):')
    for p in PROBLEMS:
        print('  *** ' + p)
    S['problems'] = PROBLEMS
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(S, fh, indent=1, ensure_ascii=False)
    print(f'\nsummary: {a.out}')
    return 1 if PROBLEMS else 0


if __name__ == '__main__':
    raise SystemExit(main())
