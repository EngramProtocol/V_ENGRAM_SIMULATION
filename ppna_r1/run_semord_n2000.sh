#!/bin/bash
# =============================================================================
# SEMORD ở 2.000 peer (ppna-r1-semord4): điểm quy mô thứ hai cho phép so với Semord (R1-5). Chạy
# sau run_semord.sh và dùng lại setup, dữ liệu, build của nó. Hướng dẫn: ppna_r1/README_semord.md
#
#   bash ppna_r1/run_semord_n2000.sh
#
# Bước (STAGES, mặc định tất cả): artifact (cấu hình VHash cho overlay 2.000 node: dùng cấu hình cố
# định sel/<ds>_sel_n2000.json, không có thì chạy bộ chọn trên validation; huấn luyện 10 seed thành
# model vortex_v1_<ds>_n2000_s<seed>; build lại vortex_bench), vk (V-Engram N = 2.000, K = 4 = N/500,
# thêm K = 2 và 10), val (quét tham số truy vấn của Semord trên validation), test (10 seed), report.
# Tuỳ chọn: SEMORD_ROOT (~/semord_src), PARALLEL (nproc - 1; mỗi tiến trình Semord khoảng 2,4 GB RAM),
# PY, BUDGETS (ngân sách B của Semord, mặc định 53,97: bằng số peer V-Engram K = 2 và K = 4 liên lạc
# ở 2.000 peer, trung bình 10 seed trên cả hai corpus là 52,7 và 97,2).
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
N=2000
LOG=ppna_r1/logs_semord_n$N
OUT=ppna_r1/out_semord
mkdir -p "$LOG" "$OUT"
if [ -z "${PY:-}" ]; then
    if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
export PY
STAGES="${STAGES:-artifact vk val test report}"
NP=$(nproc)
PARALLEL="${PARALLEL:-$(( NP > 1 ? NP - 1 : 1 ))}"
BUDGETS="${BUDGETS:-53,97}"
export SEMORD_ROOT="${SEMORD_ROOT:-$HOME/semord_src}"
export PATH="$SEMORD_ROOT/tools/cmake/cmake/data/bin:$PATH"
WORK="$SEMORD_ROOT/work"
DATA="$SEMORD_ROOT/data"
BENCH="$SEMORD_ROOT/Vortex_system/build/vortex_bench"
if [ ! -x "$BENCH" ] || [ ! -f "$DATA/code/code_val_query.fvecs" ]; then
    echo "Chưa có build hoặc dữ liệu của Semord: chạy ppna_r1/run_semord.sh trước. Dừng."
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
    echo "N = $N | nproc = $NP | PARALLEL = $PARALLEL | BUDGETS = $BUDGETS | SEMORD_ROOT = $SEMORD_ROOT | STAGES = $STAGES"
    free -g | head -2
    "$PY" -c "import sys, numpy; print('python', sys.version.split()[0], '| numpy', numpy.__version__)"
    g++ --version 2>/dev/null | head -1; cmake --version 2>/dev/null | head -1
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

for st in $STAGES; do
    echo "$(date -u +%FT%TZ) == $st ==" | tee -a "$LOG/run.log"
    case $st in
    artifact)
        LH="$SEMORD_ROOT/LearnedHash" VX="$SEMORD_ROOT/Vortex_system" DATA="$DATA" WORK="$WORK" NODES=$N \
            bash ppna_r1/semord/semord_pipeline.sh 2>&1 | grep -v "^+" | tee "$LOG/artifact.log"
        grep -q "PIPELINE XONG" "$LOG/artifact.log" || { echo "ARTIFACT LỖI, dừng."; exit 1; }
        mkdir -p "$OUT/sel_n$N"
        cp "$WORK"/vh_n$N/*_sel.json "$WORK"/vh_n$N/artifact_configs.json "$OUT/sel_n$N/" 2>/dev/null
        ;;
    vk)
        "$PY" ppna_r1/semord/jobs_vk.py --nodes $N --k 4 --extra-k 2,10 --write "$LOG/jobs_vk.jsonl"
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/jobs_vk.jsonl" --parallel "$PARALLEL" \
            --big-parallel 1 --min-free-gb 2 --log "$LOG/vk.log" --logdir "$LOG"
        ;;
    val)
        "$PY" ppna_r1/semord/run_semord.py --bench "$BENCH" --data "$DATA" --out "$OUT/runs_n$N" \
            --stage val --nodes $N --budgets "$BUDGETS" --method-suffix "_n$N" --workers "$PARALLEL" \
            2>&1 | tee "$LOG/val.log"
        ;;
    test)
        "$PY" ppna_r1/semord/run_semord.py --bench "$BENCH" --data "$DATA" --out "$OUT/runs_n$N" \
            --stage test --nodes $N --test-budgets "$BUDGETS" --method-suffix "_n$N" --workers "$PARALLEL" \
            2>&1 | tee "$LOG/test.log"
        ;;
    report)
        "$PY" ppna_r1/semord/aggregate_semord.py --semord "$OUT/runs_n$N" --vengram "$OUT/vk$N" --nodes $N \
            --ref-k 4,2 --out ppna_r1/semord_summary_n$N.json > ppna_r1/semord_report_n$N.txt 2>&1
        cat ppna_r1/semord_report_n$N.txt
        ;;
    *) echo "Không biết bước '$st'"; exit 1 ;;
    esac
done
echo "XONG SEMORD N2000" | tee -a "$LOG/run.log"
