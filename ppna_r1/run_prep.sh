#!/bin/bash
# Chuẩn bị dữ liệu cho đợt 1, chạy trên server thay cho Colab.
# Hướng dẫn: ppna_r1/README_prep.md
#
#   tmux new -s prep -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_prep.sh"
#
# Mỗi bước xong để lại file .ok trong ppna_r1/logs_prep/; chạy lại lệnh trên thì
# bước đã xong được bỏ qua, bước nhúng dở tiếp tục từ khối cuối đã lưu.
# Chạy riêng vài bước: STAGES="p1 report" bash ppna_r1/run_prep.sh
set -u
cd "$(dirname "$0")/.." || exit 1
LOGD=ppna_r1/logs_prep
mkdir -p "$LOGD" ppna_r1/prep_out
PY="${PY_PREP:-venv_prep/bin/python}"
STAGES="${STAGES:-smoke p1 p3 p4 e5 jina report}"
export PREP_THREADS="${PREP_THREADS:-$(nproc)}"
export OMP_NUM_THREADS="$PREP_THREADS" MKL_NUM_THREADS="$PREP_THREADS"
export TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "Không thấy $PY. Tạo venv_prep theo ppna_r1/README_prep.md trước."
    exit 1
fi

{
    echo "HEAD = $(git rev-parse --short HEAD) | tag = $(git describe --tags --exact-match 2>/dev/null || echo '-')"
    echo "file đã track bị sửa (phải trống):"
    git status --short | grep -v '^??'
    echo "nproc = $(nproc) | PREP_THREADS = $PREP_THREADS"
    free -g | head -2
    df -h . | tail -1
    echo "HF_ENDPOINT = ${HF_ENDPOINT:-mặc định}"
    "$PY" -c "import sys; sys.path.insert(0, 'ppna_r1/prep'); from common import lib_versions; print(lib_versions())"
} > "$LOGD/env.txt" 2>&1

run_stage() {
    local name=$1; shift
    if [ "$name" != report ] && [ -f "$LOGD/$name.ok" ]; then
        echo "$(date -u +%FT%TZ) $name đã xong trước đó, bỏ qua" | tee -a "$LOGD/run.log"
        return 0
    fi
    echo "$(date -u +%FT%TZ) bắt đầu $name" | tee -a "$LOGD/run.log"
    local t0 rc dt
    t0=$(date +%s)
    "$@" > "$LOGD/$name.log" 2>&1
    rc=$?
    dt=$(( $(date +%s) - t0 ))
    echo "$(date -u +%FT%TZ) $name mã thoát $rc, $dt giây" | tee -a "$LOGD/run.log"
    if [ $rc -ne 0 ]; then
        echo "DỪNG: $name lỗi, xem $LOGD/$name.log" | tee -a "$LOGD/run.log"
        tail -20 "$LOGD/$name.log"
        exit $rc
    fi
    touch "$LOGD/$name.ok"
}

for st in $STAGES; do
    case $st in
        smoke)
            run_stage smoke_p1   "$PY" ppna_r1/prep/p1_validation.py --smoke
            run_stage smoke_p3   "$PY" ppna_r1/prep/p3_scales.py --smoke
            run_stage smoke_p4   "$PY" ppna_r1/prep/p4_pq_variants.py --smoke
            run_stage smoke_e5   "$PY" ppna_r1/prep/p2_models.py --model e5 --smoke
            run_stage smoke_jina "$PY" ppna_r1/prep/p2_models.py --model jina --smoke
            grep -h "ước cả corpus" "$LOGD"/smoke_e5.log "$LOGD"/smoke_jina.log | tee -a "$LOGD/run.log"
            ;;
        p1)     run_stage p1     "$PY" ppna_r1/prep/p1_validation.py ;;
        p3)     run_stage p3     "$PY" ppna_r1/prep/p3_scales.py ;;
        p4)     run_stage p4     "$PY" ppna_r1/prep/p4_pq_variants.py ;;
        e5)     run_stage e5     "$PY" ppna_r1/prep/p2_models.py --model e5 ;;
        jina)   run_stage jina   "$PY" ppna_r1/prep/p2_models.py --model jina ;;
        report) run_stage report "$PY" ppna_r1/prep/report.py ;;
        *) echo "Không biết bước '$st'"; exit 1 ;;
    esac
done
echo "XONG CHUẨN BỊ DỮ LIỆU" | tee -a "$LOGD/run.log"
