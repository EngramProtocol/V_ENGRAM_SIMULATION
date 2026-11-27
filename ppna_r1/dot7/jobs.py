"""Job list of batch dot7 (ppna-r1-dot7): bits per PQ index under the reference model. Same job
format and runner as dot1 (ppna_r1/dot1/runner.py).

- pq:  the principal configuration of dot1 group t4 (N = 10,000, L = 5, T = 8, K = 20, r = 1,
       c = 16, kappa = 30, 500 test queries, column-normalized Achlioptas projections, per-table
       statistics) with m = 512 and q_PQ = 4, 6, or 8 bits per index, CodeSearchNet and SciFact,
       ten seeds. q = 8 is the command of t4 (semantic) with another output file, so its results
       must equal ppna_r1/out_dot1/t4; aggregate.py checks this.
- sm:  smoke test: 2,000 peers, 5 queries, q_PQ = 4 and 6 on both corpora.

The codebooks with q_PQ = 4 and 6 come from prep/p5_pq_bits.py (stage prep of run_dot7.sh).
"""
import importlib.util
import json
import os

OUT = 'ppna_r1/out_dot7'
SMOKE_OUT = 'ppna_r1/logs_dot7/smoke/out'
SEEDS_ENV = os.environ.get('SEEDS')
CORPORA = ('code', 'scifact')
BITS = (4, 6, 8)

GROUPS = {
    'pq': 'Table 11: m = 512 with q_PQ = 4, 6, 8 bits per index, two corpora, ten seeds',
    'sm': 'smoke: 2,000 peers, 5 queries, q_PQ = 4 and 6',
}


def _load(name, rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', rel)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D1 = _load('dot1_jobs', 'dot1/jobs.py')
SEEDS = [int(s) for s in SEEDS_ENV.split(',')] if SEEDS_ENV else D1.SEEDS


def variant(q):
    """Suffix of the PQ files: the shipped m = 512 codebook has q_PQ = 8."""
    return 'm512' if q == 8 else f'm512q{q}'


def build(groups=None):
    J = []
    want = (lambda g: True) if not groups else (lambda g: g in groups)
    if want('pq'):
        for s in SEEDS:
            for ds in CORPORA:
                for q in BITS:
                    J.append(D1.v2('pq', f'{ds}_q{q}', ds, s, pq=variant(q), per_table=True,
                                   est=45, out_root=OUT))
    if want('sm'):
        for ds in CORPORA:
            for q in (4, 6):
                j = D1.v2('sm', f'{ds}_q{q}', ds, SEEDS[0], nodes=2000, nq=5, pq=variant(q),
                          per_table=True, out_root=SMOKE_OUT)
                j['prio'], j['timeout'] = 0, 1800
                J.append(j)
    ids = [j['id'] for j in J]
    assert len(ids) == len(set(ids)), 'duplicate job id'
    return J


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--groups', default='', help='pq, sm (comma-separated)')
    ap.add_argument('--write', required=True)
    a = ap.parse_args()
    jobs = build(set(a.groups.split(',')) if a.groups else None)
    os.makedirs(os.path.dirname(a.write) or '.', exist_ok=True)
    with open(a.write, 'w', encoding='utf-8') as fh:
        for j in jobs:
            fh.write(json.dumps(j, ensure_ascii=False) + '\n')
    print(f'{len(jobs)} jobs -> {a.write}')
