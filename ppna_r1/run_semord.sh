#!/bin/bash
# =============================================================================
# SEMORD (ppna-r1-semord2): so V-Engram với Semord (arXiv 2609.25514) bằng artifact của tác giả,
# cho R1-5. Hướng dẫn: ppna_r1/README_semord.md
#
#   source venv/bin/activate
#   tmux new -s semord -d "bash ~/V_ENGRAM_SIMULATION/ppna_r1/run_semord.sh"
#
# Bước (STAGES, mặc định tất cả): setup (clone và build artifact ở commit ghim, ngoài repo),
# data (đổi embedding sang fvecs), artifact (chọn cấu hình VHash trên validation, huấn luyện 10
# seed, build vortex_bench), vk (V-Engram N = 1.000, 20 job), val (quét tham số truy vấn của
# Semord trên validation), test (10 seed), report.
# Tuỳ chọn: SEMORD_ROOT (~/semord_src), PARALLEL (nproc - 1), PY.
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=ppna_r1/logs_semord
OUT=ppna_r1/out_semord
mkdir -p "$LOG" "$OUT"
if [ -z "${PY:-}" ]; then
    if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
export PY
STAGES="${STAGES:-setup data artifact vk val test report}"
NP=$(nproc)
PARALLEL="${PARALLEL:-$(( NP > 1 ? NP - 1 : 1 ))}"
export SEMORD_ROOT="${SEMORD_ROOT:-$HOME/semord_src}"
# máy không có cmake thì setup cài cmake bằng pip vào đây; bước artifact cũng cần thấy nó
export PATH="$SEMORD_ROOT/tools/cmake/cmake/data/bin:$PATH"
WORK="$SEMORD_ROOT/work"
DATA="$SEMORD_ROOT/data"
BENCH="$SEMORD_ROOT/Vortex_system/build/vortex_bench"
mkdir -p "$WORK" "$DATA"

DIRTY=$(git status --short | grep -v '^??')
if [ -n "$DIRTY" ] && [ "${ALLOW_DIRTY:-0}" != "1" ]; then
    echo "Có file đã track bị sửa; mọi kết quả phải sinh từ đúng commit của tag. Dừng."
    echo "$DIRTY"
    exit 1
fi
{
    echo "HEAD = $(git rev-parse --short HEAD) | tag = $(git describe --tags --exact-match 2>/dev/null || echo '-')"
    echo "nproc = $NP | PARALLEL = $PARALLEL | SEMORD_ROOT = $SEMORD_ROOT | STAGES = $STAGES"
    free -g | head -2
    "$PY" -c "import sys, numpy; print('python', sys.version.split()[0], '| numpy', numpy.__version__)"
    g++ --version 2>/dev/null | head -1; cmake --version 2>/dev/null | head -1
    ldconfig -p | grep -E "libblas|libopenblas|liblapack" | head -3
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

for st in $STAGES; do
    echo "$(date -u +%FT%TZ) == $st ==" | tee -a "$LOG/run.log"
    case $st in
    setup)
        bash ppna_r1/semord/setup_semord.sh 2>&1 | tee "$LOG/setup.log"
        grep -q "SETUP XONG" "$LOG/setup.log" || { echo "SETUP LỖI, dừng. Gửi $LOG/setup.log và $SEMORD_ROOT/*.log"; exit 1; }
        ;;
    data)
        "$PY" ppna_r1/semord/to_vecs.py data "$DATA" 2>&1 | tee "$LOG/data.log"
        ls "$DATA"/code/code_val_query.fvecs "$DATA"/scifact/scifact_val_query.fvecs > /dev/null || {
            echo "Thiếu query validation (data/*_val_query_embeddings.npy). Dừng."; exit 1; }
        ;;
    artifact)
        LH="$SEMORD_ROOT/LearnedHash" VX="$SEMORD_ROOT/Vortex_system" DATA="$DATA" WORK="$WORK" NODES=1000 \
            bash ppna_r1/semord/semord_pipeline.sh 2>&1 | grep -v "^+" | tee "$LOG/artifact.log"
        grep -q "PIPELINE XONG" "$LOG/artifact.log" || { echo "ARTIFACT LỖI, dừng."; exit 1; }
        cp "$WORK"/vh_n1000/*_sel.json "$WORK"/vh_n1000/artifact_configs.json "$OUT"/ 2>/dev/null
        ;;
    vk)
        "$PY" ppna_r1/semord/jobs_vk.py --write "$LOG/jobs_vk.jsonl"
        "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/jobs_vk.jsonl" --parallel "$PARALLEL" \
            --big-parallel 1 --min-free-gb 2 --log "$LOG/vk.log" --logdir "$LOG"
        ;;
    val)
        "$PY" ppna_r1/semord/run_semord.py --bench "$BENCH" --data "$DATA" --out "$OUT/runs" \
            --stage val --nodes 1000 --workers "$PARALLEL" 2>&1 | tee "$LOG/val.log"
        ;;
    test)
        "$PY" ppna_r1/semord/run_semord.py --bench "$BENCH" --data "$DATA" --out "$OUT/runs" \
            --stage test --nodes 1000 --workers "$PARALLEL" 2>&1 | tee "$LOG/test.log"
        ;;
    report)
        "$PY" ppna_r1/semord/aggregate_semord.py --semord "$OUT/runs" --vengram "$OUT/vk1000" \
            --out ppna_r1/semord_summary.json > ppna_r1/semord_report.txt 2>&1
        cat ppna_r1/semord_report.txt
        ;;
    *) echo "Không biết bước '$st'"; exit 1 ;;
    esac
done
echo "XONG SEMORD" | tee -a "$LOG/run.log"
