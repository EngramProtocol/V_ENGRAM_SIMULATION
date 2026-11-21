#!/bin/bash
# =============================================================================
# ĐỢT 4 (ppna-r1-dot4): L = 8 bảng trên mô hình iterative cho mục chọn điểm vận hành (R2-2),
# join đầy đủ và join cũ, kèm hai điểm lý tưởng tương ứng của đợt 1 để ghép cặp theo seed.
# Hướng dẫn: ppna_r1/README_dot4.md
#
#   source venv/bin/activate
#   tmux new -s dot4 -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_dot4.sh"
#
# Ba bước (STAGES, mặc định cả ba): smoke, run (80 job), report
# (ppna_r1/dot4_report.txt và ppna_r1/dot4_summary.json).
# Chạy lại đúng lệnh sau khi bị ngắt: job đã xong với cùng commit được bỏ qua.
# Tuỳ chọn: PARALLEL (mặc định nproc - 1), MIN_FREE_GB (4), RUN_GROUPS, PY.
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=ppna_r1/logs_dot4
mkdir -p "$LOG/smoke"
if [ -z "${PY:-}" ]; then
    if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
export PY
STAGES="${STAGES:-smoke run report}"
NP=$(nproc)
PARALLEL="${PARALLEL:-$(( NP > 1 ? NP - 1 : 1 ))}"
BIG_PARALLEL="${BIG_PARALLEL:-4}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
RUN_GROUPS="${RUN_GROUPS:-}"
GROUPS_ARG=""
[ -n "$RUN_GROUPS" ] && GROUPS_ARG="--groups $(echo "$RUN_GROUPS" | tr ' ' ',')"

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
    echo "nproc = $NP | PARALLEL = $PARALLEL | BIG_PARALLEL = $BIG_PARALLEL | MIN_FREE_GB = $MIN_FREE_GB"
    echo "RUN_GROUPS = ${RUN_GROUPS:-tất cả} | STAGES = $STAGES"
    free -g | head -2
    df -h . | tail -1
    "$PY" -c "import sys, numpy, simpy; print('python', sys.version.split()[0], '| numpy', numpy.__version__, '| simpy', simpy.__version__)"
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

for st in $STAGES; do
    case $st in
    smoke)
        echo "$(date -u +%FT%TZ) == smoke test ==" | tee -a "$LOG/run.log"
        "$PY" ppna_r1/dot4/jobs.py --smoke --write "$LOG/smoke/jobs.jsonl" > /dev/null
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/smoke/jobs.jsonl" --parallel "$PARALLEL" \
            --big-parallel "$BIG_PARALLEL" --min-free-gb "$MIN_FREE_GB" \
            --log "$LOG/smoke/run.log" --logdir "$LOG/smoke"
        rc=$?
        "$PY" ppna_r1/dot4/aggregate.py --smoke-check "$LOG/smoke/out" | tee "$LOG/smoke/check.txt"
        rc2=${PIPESTATUS[0]}
        if [ $rc -ne 0 ] || [ $rc2 -ne 0 ]; then
            echo "SMOKE TEST LỖI, dừng. Gửi thư mục $LOG/smoke (log từng job nằm trong đó)." | tee -a "$LOG/run.log"
            exit 1
        fi
        echo "$(date -u +%FT%TZ) smoke test đạt" | tee -a "$LOG/run.log"
        ;;
    run)
        "$PY" ppna_r1/dot4/jobs.py --write "$LOG/jobs.jsonl" | tee "$LOG/jobs_summary.txt"
        # shellcheck disable=SC2086
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/jobs.jsonl" --parallel "$PARALLEL" \
            --big-parallel "$BIG_PARALLEL" --min-free-gb "$MIN_FREE_GB" $GROUPS_ARG \
            --log "$LOG/run.log" --logdir "$LOG"
        echo "$(date -u +%FT%TZ) runner mã thoát $?" | tee -a "$LOG/run.log"
        ;;
    report)
        "$PY" ppna_r1/dot4/aggregate.py --out-root ppna_r1/out_dot4 \
            --summary ppna_r1/dot4_summary.json > ppna_r1/dot4_report.txt 2>&1
        echo "$(date -u +%FT%TZ) report mã thoát $?: ppna_r1/dot4_report.txt" | tee -a "$LOG/run.log"
        tail -5 ppna_r1/dot4_report.txt
        ;;
    *) echo "Không biết bước '$st'"; exit 1 ;;
    esac
done
echo "XONG ĐỢT 4" | tee -a "$LOG/run.log"
