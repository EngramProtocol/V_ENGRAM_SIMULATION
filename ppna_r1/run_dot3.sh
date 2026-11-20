#!/bin/bash
# =============================================================================
# ĐỢT 3 (ppna-r1-dot3): phần iterative còn lại. Bảng 5 trên iterative, 50.000 peer,
# workload R1-4, join đầy đủ như Kademlia gốc (làm mới k-bucket), Bucket-LSH với
# ingest chạy hết ngân sách. Hướng dẫn: ppna_r1/README_dot3.md
#
#   source venv/bin/activate
#   tmux new -s dot3 -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_dot3.sh"
#
# Ba bước (STAGES, mặc định cả ba): smoke, run (220 job), report
# (ppna_r1/dot3_report.txt và ppna_r1/dot3_summary.json).
# Chạy lại đúng lệnh sau khi bị ngắt: job đã xong với cùng commit được bỏ qua.
# Tuỳ chọn: PARALLEL (mặc định nproc - 1), BIG_PARALLEL (4: số job 50.000 peer chạy
#           cùng lúc, mỗi job tới khoảng 3 GB RAM), MIN_FREE_GB (4), RUN_GROUPS, PY.
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=ppna_r1/logs_dot3
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
    echo "đợt 2: $(grep -c 'XONG ĐỢT 2' ppna_r1/logs_dot2/run.log 2>/dev/null || echo 0) lần XONG; $(tail -1 ppna_r1/dot2_report.txt 2>/dev/null || echo 'chưa có ppna_r1/dot2_report.txt')"
    echo "kết quả đợt 1: $(ls ppna_r1/out_dot1 2>/dev/null | wc -l) nhóm | đợt 2: $(ls ppna_r1/out_dot2 2>/dev/null | wc -l) nhóm"
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

for st in $STAGES; do
    case $st in
    smoke)
        echo "$(date -u +%FT%TZ) == smoke test ==" | tee -a "$LOG/run.log"
        "$PY" ppna_r1/dot3/jobs.py --smoke --write "$LOG/smoke/jobs.jsonl" > /dev/null
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/smoke/jobs.jsonl" --parallel "$PARALLEL" \
            --big-parallel "$BIG_PARALLEL" --min-free-gb "$MIN_FREE_GB" \
            --log "$LOG/smoke/run.log" --logdir "$LOG/smoke"
        rc=$?
        "$PY" ppna_r1/dot3/aggregate.py --smoke-check "$LOG/smoke/out" | tee "$LOG/smoke/check.txt"
        rc2=${PIPESTATUS[0]}
        if [ $rc -ne 0 ] || [ $rc2 -ne 0 ]; then
            echo "SMOKE TEST LỖI, dừng. Gửi thư mục $LOG/smoke (log từng job nằm trong đó)." | tee -a "$LOG/run.log"
            exit 1
        fi
        echo "$(date -u +%FT%TZ) smoke test đạt" | tee -a "$LOG/run.log"
        ;;
    run)
        "$PY" ppna_r1/dot3/jobs.py --write "$LOG/jobs.jsonl" | tee "$LOG/jobs_summary.txt"
        # shellcheck disable=SC2086
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/jobs.jsonl" --parallel "$PARALLEL" \
            --big-parallel "$BIG_PARALLEL" --min-free-gb "$MIN_FREE_GB" $GROUPS_ARG \
            --log "$LOG/run.log" --logdir "$LOG"
        echo "$(date -u +%FT%TZ) runner mã thoát $?" | tee -a "$LOG/run.log"
        ;;
    report)
        "$PY" ppna_r1/dot3/aggregate.py --out-root ppna_r1/out_dot3 \
            --summary ppna_r1/dot3_summary.json > ppna_r1/dot3_report.txt 2>&1
        echo "$(date -u +%FT%TZ) report mã thoát $?: ppna_r1/dot3_report.txt" | tee -a "$LOG/run.log"
        tail -5 ppna_r1/dot3_report.txt
        ;;
    *) echo "Không biết bước '$st'"; exit 1 ;;
    esac
done
echo "XONG ĐỢT 3" | tee -a "$LOG/run.log"
