#!/bin/bash
# =============================================================================
# ĐỢT 5 (ppna-r1-dot5): Bảng 10 (churn) trên mô hình iterative, ba cấu hình, 10 seed, ghép cặp theo
# seed với số lý tưởng của đợt 1 (ppna_r1/out_dot1/churn).
# Hướng dẫn: ppna_r1/README_dot5.md
#
#   source venv/bin/activate
#   tmux new -s dot5 -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_dot5.sh"
#
# Bốn bước (STAGES, mặc định cả bốn): smoke, run (30 job), t0 (R@5 lúc t = 0 của mô hình lý tưởng, vài phút),
# report (ppna_r1/dot5_report.txt và ppna_r1/dot5_summary.json).
# Chạy lại đúng lệnh sau khi bị ngắt: job đã xong với cùng commit được bỏ qua, job đang dở chạy tiếp
# từ checkpoint của nó (<file kết quả>.ckpt).
# Tuỳ chọn: PARALLEL (mặc định nproc - 1), MIN_FREE_GB (4), IDEAL_ROOT, STATIC_ROOT, PY.
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=ppna_r1/logs_dot5
mkdir -p "$LOG/smoke"
if [ -z "${PY:-}" ]; then
    if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
export PY
STAGES="${STAGES:-smoke run t0 report}"
NP=$(nproc)
PARALLEL="${PARALLEL:-$(( NP > 1 ? NP - 1 : 1 ))}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
IDEAL_ROOT="${IDEAL_ROOT:-ppna_r1/out_dot1/churn}"
STATIC_ROOT="${STATIC_ROOT:-ppna_r1/out_dot3/tk_r}"

if ! "$PY" -c "import numpy, simpy" 2>/dev/null; then
    echo "Thiếu numpy hoặc simpy trong $PY. Chạy: source venv/bin/activate"
    exit 1
fi
DIRTY=$(git status --short | grep -v '^??')
if [ -n "$DIRTY" ] && [ "${ALLOW_DIRTY:-0}" != "1" ]; then
    echo "Có file đã track bị sửa; mọi kết quả phải sinh từ đúng commit của tag. Dừng."
    echo "$DIRTY"
    exit 1
fi

{
    echo "HEAD = $(git rev-parse --short HEAD) | tag = $(git describe --tags --exact-match 2>/dev/null || echo '-')"
    echo "file đã track bị sửa (phải trống):"
    echo "$DIRTY"
    echo "nproc = $NP | PARALLEL = $PARALLEL | MIN_FREE_GB = $MIN_FREE_GB | STAGES = $STAGES"
    echo "IDEAL_ROOT = $IDEAL_ROOT | STATIC_ROOT = $STATIC_ROOT"
    free -g | head -2
    df -h . | tail -1
    "$PY" -c "import sys, numpy, simpy; print('python', sys.version.split()[0], '| numpy', numpy.__version__, '| simpy', simpy.__version__)"
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

for st in $STAGES; do
    case $st in
    smoke)
        echo "$(date -u +%FT%TZ) == smoke test ==" | tee -a "$LOG/run.log"
        "$PY" ppna_r1/dot5/jobs.py --smoke --write "$LOG/smoke/jobs.jsonl" > /dev/null
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/smoke/jobs.jsonl" --parallel "$PARALLEL" \
            --min-free-gb "$MIN_FREE_GB" --log "$LOG/smoke/run.log" --logdir "$LOG/smoke"
        rc=$?
        "$PY" ppna_r1/dot5/jobs.py --resume-test
        rc1=$?
        "$PY" ppna_r1/dot5/aggregate.py --smoke-check "$LOG/smoke/out" | tee "$LOG/smoke/check.txt"
        rc2=${PIPESTATUS[0]}
        if [ $rc -ne 0 ] || [ $rc1 -ne 0 ] || [ $rc2 -ne 0 ]; then
            echo "SMOKE TEST LỖI, dừng. Gửi thư mục $LOG/smoke (log từng job nằm trong đó)." | tee -a "$LOG/run.log"
            exit 1
        fi
        echo "$(date -u +%FT%TZ) smoke test đạt" | tee -a "$LOG/run.log"
        ;;
    run)
        "$PY" ppna_r1/dot5/jobs.py --write "$LOG/jobs.jsonl" | tee "$LOG/jobs_summary.txt"
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/jobs.jsonl" --parallel "$PARALLEL" \
            --min-free-gb "$MIN_FREE_GB" --log "$LOG/run.log" --logdir "$LOG"
        rc=$?
        echo "$(date -u +%FT%TZ) runner mã thoát $rc" | tee -a "$LOG/run.log"
        ;;
    t0)
        OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 "$PY" ppna_r1/dot5/ideal_t0.py --meta-anchors 1 4 \
            --out-dir ppna_r1/out_dot5/ideal_t0 | tee "$LOG/ideal_t0.log"
        ;;
    report)
        "$PY" ppna_r1/dot5/aggregate.py --out-root ppna_r1/out_dot5 --ideal-root "$IDEAL_ROOT" \
            --static-root "$STATIC_ROOT" --ideal-t0-root ppna_r1/out_dot5/ideal_t0 \
            --summary ppna_r1/dot5_summary.json > ppna_r1/dot5_report.txt 2>&1
        rc=$?
        echo "$(date -u +%FT%TZ) report mã thoát $rc: ppna_r1/dot5_report.txt" | tee -a "$LOG/run.log"
        tail -5 ppna_r1/dot5_report.txt
        ;;
    *) echo "Không biết bước '$st'"; exit 1 ;;
    esac
done
echo "XONG ĐỢT 5" | tee -a "$LOG/run.log"
