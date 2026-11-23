#!/bin/bash
# =============================================================================
# SEMORD so với V-Engram ở điểm vận hành L = 8, T = 5 (ppna-r1-semord5), cho R1-5. Chạy sau
# run_semord.sh và run_semord_n2000.sh: dùng lại setup, dữ liệu, build, model VHash và kết quả của
# hai script đó. Hướng dẫn: ppna_r1/README_semord.md, mục "Điểm vận hành L = 8".
#
#   bash ppna_r1/run_semord_l8.sh
#
# Với mỗi N trong NODES_LIST (mặc định 1000 2000), các bước (STAGES, mặc định tất cả):
#   vk      V-Engram L = 8 (biến thể L8_T5 và L8_T8 trên cùng một mạng), K = N/500, join đầy đủ,
#           code và SciFact, 10 seed: 20 job, nhóm out_semord/vk<N>_L8
#   budget  ngân sách B của Semord = số peer V-Engram L8_T5 liên lạc, trung bình 10 seed trên hai
#           corpus, làm tròn (cùng cách đặt B = 49, 53, 97 trước đây); ghi out_semord/budget_l8_n<N>.json
#   val     chọn kế hoạch truy vấn của Semord trên query validation ở ngân sách B (gộp vào
#           val_best.json, các ngân sách cũ giữ nguyên)
#   test    10 seed, kế hoạch đã chọn, kèm kế hoạch mặc định khi B ≤ 64 (như các ngân sách khác)
#   report  ppna_r1/semord_report_l8_n<N>.txt và ppna_r1/semord_summary_l8_n<N>.json: V-Engram cấu
#           hình chính và L = 8, Semord ở mọi ngân sách, hiệu ghép theo seed với cả hai cấu hình
# Tuỳ chọn: SEMORD_ROOT (~/semord_src), PARALLEL (nproc - 1; mỗi tiến trình Semord khoảng 0,8 GB RAM
# ở 1.000 node, 2,4 GB ở 2.000), PY, NODES_LIST.
# Chạy lại đúng lệnh sau khi bị ngắt: job V-Engram đã xong với cùng commit và lần chạy Semord đã có
# kết quả với đúng model được bỏ qua.
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=ppna_r1/logs_semord_l8
OUT=ppna_r1/out_semord
mkdir -p "$LOG" "$OUT"
if [ -z "${PY:-}" ]; then
    if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
export PY
STAGES="${STAGES:-vk budget val test report}"
NODES_LIST="${NODES_LIST:-1000 2000}"
NP=$(nproc)
PARALLEL="${PARALLEL:-$(( NP > 1 ? NP - 1 : 1 ))}"
export SEMORD_ROOT="${SEMORD_ROOT:-$HOME/semord_src}"
export PATH="$SEMORD_ROOT/tools/cmake/cmake/data/bin:$PATH"
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
    echo "NODES_LIST = $NODES_LIST | nproc = $NP | PARALLEL = $PARALLEL | SEMORD_ROOT = $SEMORD_ROOT | STAGES = $STAGES"
    free -g | head -2
    "$PY" -c "import sys, numpy; print('python', sys.version.split()[0], '| numpy', numpy.__version__)"
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

budget_of() {
    "$PY" -c "import json, sys; print(json.load(open(sys.argv[1]))['B'])" "$OUT/budget_l8_n$1.json"
}

for N in $NODES_LIST; do
    K=$(( N / 500 ))
    if [ "$N" = 1000 ]; then RUNS="$OUT/runs"; SUF=""; else RUNS="$OUT/runs_n$N"; SUF="_n$N"; fi
    if [ ! -f "$RUNS/val_best.json" ]; then
        echo "Chưa có kết quả Semord ở N = $N ($RUNS): chạy run_semord.sh và run_semord_n2000.sh trước. Dừng."
        exit 1
    fi
    for st in $STAGES; do
        echo "$(date -u +%FT%TZ) == N = $N: $st ==" | tee -a "$LOG/run.log"
        case $st in
        vk)
            "$PY" ppna_r1/semord/jobs_vk.py --nodes "$N" --k "$K" --l8 --write "$LOG/jobs_vk_n$N.jsonl"
            "$PY" ppna_r1/dot1/runner.py --jobs "$LOG/jobs_vk_n$N.jsonl" --parallel "$PARALLEL" \
                --big-parallel 1 --min-free-gb 2 --log "$LOG/vk_n$N.log" --logdir "$LOG"
            rc=$?
            if [ $rc -ne 0 ]; then echo "V-Engram L = 8 lỗi (mã $rc), dừng." | tee -a "$LOG/run.log"; exit 1; fi
            ;;
        budget)
            "$PY" - "$OUT/vk${N}_L8" "$OUT/budget_l8_n$N.json" <<'PYEOF' | tee -a "$LOG/run.log"
import glob, json, statistics as st, sys
root, out = sys.argv[1], sys.argv[2]
per = {}
for f in sorted(glob.glob(root + '/*_s*.json')):
    d = json.load(open(f))
    per[f"{d['dataset']}/s{d['seed']}"] = d['variants']['L8_T5']['mean_contacted']
if len(per) != 20:
    sys.exit(f'cần 20 file kết quả L = 8 trong {root}, có {len(per)}')
m = st.mean(per.values())
B = int(round(m))
json.dump({'B': B, 'mean_contacted': m, 'per_run': per}, open(out, 'w'), indent=1)
print(f'ngân sách Semord B = {B} (V-Engram L8_T5 liên lạc trung bình {m:.2f} peer)')
PYEOF
            [ "${PIPESTATUS[0]}" -eq 0 ] || exit 1
            ;;
        val)
            B=$(budget_of "$N") || exit 1
            "$PY" ppna_r1/semord/run_semord.py --bench "$BENCH" --data "$DATA" --out "$RUNS" --stage val \
                --nodes "$N" --budgets "$B" --method-suffix "$SUF" --workers "$PARALLEL" 2>&1 | tee "$LOG/val_n$N.log"
            [ "${PIPESTATUS[0]}" -eq 0 ] || { echo "VAL LỖI ở N = $N, dừng." | tee -a "$LOG/run.log"; exit 1; }
            ;;
        test)
            B=$(budget_of "$N") || exit 1
            "$PY" ppna_r1/semord/run_semord.py --bench "$BENCH" --data "$DATA" --out "$RUNS" --stage test \
                --nodes "$N" --test-budgets "$B" --method-suffix "$SUF" --workers "$PARALLEL" 2>&1 | tee "$LOG/test_n$N.log"
            [ "${PIPESTATUS[0]}" -eq 0 ] || { echo "TEST LỖI ở N = $N, dừng." | tee -a "$LOG/run.log"; exit 1; }
            ;;
        report)
            "$PY" ppna_r1/semord/aggregate_semord.py --semord "$RUNS" --vengram "$OUT/vk$N,$OUT/vk${N}_L8" \
                --nodes "$N" --ref-k "$K" --ref-var L8_T5 --out "ppna_r1/semord_summary_l8_n$N.json" \
                > "ppna_r1/semord_report_l8_n$N.txt" 2>&1
            cat "ppna_r1/semord_report_l8_n$N.txt"
            ;;
        *) echo "Không biết bước '$st'"; exit 1 ;;
        esac
    done
done
echo "XONG SEMORD L8" | tee -a "$LOG/run.log"
