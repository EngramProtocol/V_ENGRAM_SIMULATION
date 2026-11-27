#!/bin/bash
# =============================================================================
# BATCH 7 (ppna-r1-dot7): bits per PQ index at m = 512 under the reference model (R1-1, Table 11).
# Notes: ppna_r1/README_dot7.md
#
#   bash ppna_r1/run_dot7.sh
#
# Four stages (STAGES, all four by default):
#   prep    PQ codebooks with q_PQ = 4 and 6 for code and scifact (prep/p5_pq_bits.py, a few minutes);
#           also retrains q_PQ = 8 and compares it with the shipped codebook. Runs with PY_PREP
#           (default venv_prep/bin/python, the faiss of prep step p4). Skipped once logs_dot7/prep.ok
#           exists, so a rerun never replaces the codebooks that the results were computed with.
#   smoke   2,000 peers, 5 queries, q_PQ = 4 and 6 on both corpora (under a minute)
#   run     60 jobs: principal configuration, q_PQ = 4, 6, 8, two corpora, ten seeds
#   report  ppna_r1/dot7_report.txt and ppna_r1/dot7_summary.json; regression with REF_ROOT
# Options: PARALLEL (default nproc - 1), PY, PY_PREP, REF_ROOT (default ppna_r1/out_dot1),
# SEEDS (default the ten seeds).
# Rerunning the same command after an interruption skips jobs finished with the same commit.
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=ppna_r1/logs_dot7
mkdir -p "$LOG/smoke"
if [ -z "${PY:-}" ]; then
    if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
export PY
if [ -z "${PY_PREP:-}" ]; then
    if [ -x venv_prep/bin/python ]; then PY_PREP=venv_prep/bin/python; else PY_PREP=$PY; fi
fi
STAGES="${STAGES:-prep smoke run report}"
NP=$(nproc)
PARALLEL="${PARALLEL:-$(( NP > 1 ? NP - 1 : 1 ))}"
REF_ROOT="${REF_ROOT:-ppna_r1/out_dot1}"

if ! "$PY" -c "import numpy" 2>/dev/null; then
    echo "numpy missing in $PY. Run: source venv/bin/activate"
    exit 1
fi
case " $STAGES " in
    *" prep "*)
        if [ ! -f "$LOG/prep.ok" ] && ! "$PY_PREP" -c "import faiss" 2>/dev/null; then
            echo "faiss missing in $PY_PREP. Set PY_PREP to a Python with faiss-cpu (venv_prep)."
            exit 1
        fi ;;
esac
DIRTY=$(git status --short | grep -v '^??')
if [ -n "$DIRTY" ] && [ "${ALLOW_DIRTY:-0}" != "1" ]; then
    echo "Tracked files are modified; every result must come from the commit of the tag. Stopping."
    echo "$DIRTY"
    exit 1
fi
{
    echo "HEAD = $(git rev-parse --short HEAD) | tag = $(git describe --tags --exact-match 2>/dev/null || echo '-')"
    echo "nproc = $NP | PARALLEL = $PARALLEL | STAGES = $STAGES | REF_ROOT = $REF_ROOT | SEEDS = ${SEEDS:-default}"
    free -g | head -2
    echo "PY = $PY"
    "$PY" -c "import sys, numpy; print('python', sys.version.split()[0], '| numpy', numpy.__version__)"
    echo "PY_PREP = $PY_PREP"
    "$PY_PREP" -c "import sys, numpy, faiss; print('python', sys.version.split()[0], '| numpy', numpy.__version__, '| faiss', faiss.__version__)" 2>&1
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

for st in $STAGES; do
    echo "$(date -u +%FT%TZ) == $st ==" | tee -a "$LOG/run.log"
    case $st in
    prep)
        if [ -f "$LOG/prep.ok" ]; then
            echo "prep finished before ($LOG/prep.ok), skipped" | tee -a "$LOG/run.log"
            continue
        fi
        "$PY_PREP" ppna_r1/prep/p5_pq_bits.py > "$LOG/prep.log" 2>&1
        rc=$?
        grep -v '^WARNING clustering' "$LOG/prep.log" | tail -8
        if [ $rc -ne 0 ]; then echo "prep failed (code $rc), see $LOG/prep.log" | tee -a "$LOG/run.log"; exit 1; fi
        git rev-parse --short HEAD > "$LOG/prep.ok"
        ;;
    smoke)
        rm -rf "$LOG/smoke/out"
        "$PY" ppna_r1/dot7/jobs.py --groups sm --write "$LOG/smoke/jobs.jsonl" > /dev/null
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/smoke/jobs.jsonl" --parallel "$PARALLEL" \
            --log "$LOG/smoke/run.log" --logdir "$LOG/smoke"
        rc=$?
        if [ $rc -ne 0 ]; then echo "SMOKE TEST FAILED, stopping." | tee -a "$LOG/run.log"; exit 1; fi
        "$PY" - <<'PYEOF' || { echo "SMOKE TEST FAILED, stopping." | tee -a ppna_r1/logs_dot7/run.log; exit 1; }
import glob, json
root = 'ppna_r1/logs_dot7/smoke/out/sm'
for ds in ('code', 'scifact'):
    a, b = (json.load(open(glob.glob(f'{root}/{ds}_q{q}_s*.json')[0])) for q in (4, 6))
    assert (a['pq_variant'], b['pq_variant']) == ('m512q4', 'm512q6'), 'wrong PQ files'
    for k in ('reachable_recall5', 'mean_nodes_touched', 'metadata_gini'):
        assert a[k] == b[k], f'{ds}: {k} depends on q'
    print(f"smoke {ds}: q = 4 and 6 ran with {a['n_docs']} objects; Final R@5 "
          f"{a['recall5']:.1f} and {b['recall5']:.1f}; routing identical")
PYEOF
        ;;
    run)
        "$PY" ppna_r1/dot7/jobs.py --groups pq --write "$LOG/jobs_pq.jsonl"
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/jobs_pq.jsonl" --parallel "$PARALLEL" \
            --log "$LOG/run.log" --logdir "$LOG"
        rc=$?
        if [ $rc -ne 0 ]; then echo "Group pq failed (code $rc), stopping." | tee -a "$LOG/run.log"; exit 1; fi
        ;;
    report)
        "$PY" ppna_r1/dot7/aggregate.py --root ppna_r1/out_dot7 --ref "$REF_ROOT" \
            --out ppna_r1/dot7_summary.json > ppna_r1/dot7_report.txt 2>&1
        rc=$?
        echo "$(date -u +%FT%TZ) report exit code $rc: ppna_r1/dot7_report.txt" | tee -a "$LOG/run.log"
        cat ppna_r1/dot7_report.txt
        ;;
    *) echo "Unknown stage '$st'"; exit 1 ;;
    esac
done
echo "BATCH 7 DONE" | tee -a "$LOG/run.log"
