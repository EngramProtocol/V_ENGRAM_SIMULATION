#!/bin/bash
# =============================================================================
# KIỂM CHUẨN HOÁ CỘT CHIẾU (ppna-r1-verify-norm)
#
# Câu hỏi: các file kết quả mô hình lý tưởng mà bài dùng có được sinh TRƯỚC
# commit chuẩn hoá cột chiếu d48ec0b (server nhận lúc 2026-08-17 13:45:32 UTC)
# hay không, và nếu có thì chuẩn hoá làm đổi số bao nhiêu.
#
# Cách làm:
#   1. In thời điểm ghi của mọi file result_*.json mô hình lý tưởng, chia theo
#      cấu hình, đánh dấu cấu hình nào trộn file trước và sau mốc.
#   2. Chạy lại cấu hình chính (CodeSearchNet và SciFact, 10 seed) bằng code
#      hiện tại HAI lần: NORMALIZE_ROWS=0 và NORMALIZE_ROWS=1. Ghi vào thư mục
#      riêng, KHÔNG đụng file cũ.
#   3. Đối chứng T=1 (không có phép lật): hai chế độ phải trùng từng số.
#
# Không sửa code mô phỏng. Chạy từ bất kỳ đâu; script tự cd về gốc repo.
#   PARALLEL=4 bash ppna_r1/run_verify_norm.sh
# Chạy lại sau khi bị ngắt: SKIP_DONE=1 PARALLEL=4 bash ppna_r1/run_verify_norm.sh
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1

PY=${PY:-python3}
PARALLEL=${PARALLEL:-4}
SEEDS=${SEEDS:-"20235956 1 2 3 4 5 6 7 8 9"}
CTRL_SEEDS=${CTRL_SEEDS:-"20235956 1 2"}
NODES=${NODES:-10000}
NQ=${NQ:-500}
SKIP_DONE=${SKIP_DONE:-0}
OUT=ppna_r1/out_verify_norm
LOG=ppna_r1/logs_verify_norm
mkdir -p "$OUT" "$LOG"

for ds in code scifact; do
  for f in "data/${ds}_corpus_embeddings.npy" "data/${ds}_query_embeddings.npy" \
           "data/${ds}_pq_codes_m512.npy" "data/${ds}_pq_codebook_m512.npy" \
           "data/${ds}_ground_truth.json"; do
    [ -f "$f" ] || { echo "THIẾU $f, dừng."; exit 1; }
  done
done

{
  echo "HEAD = $(git rev-parse --short HEAD) | tag = $(git describe --tags --always)"
  echo "d48ec0b nằm trong HEAD: $(git merge-base --is-ancestor d48ec0b HEAD && echo có || echo KHÔNG)"
  echo "file đã track bị sửa (phải trống):"
  git status --short | grep -v '^??' || true
  echo "reflog 16-19/8:"
  git reflog --date=iso | grep '2026-08-1[6-9]' || true
  echo "SEEDS=$SEEDS | CTRL_SEEDS=$CTRL_SEEDS | NODES=$NODES | NQ=$NQ | PARALLEL=$PARALLEL"
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

JOBS="$LOG/jobs.txt"
: > "$JOBS"
for ds in code scifact; do
  for norm in 0 1; do
    for s in $SEEDS; do echo "$ds $norm $s 8" >> "$JOBS"; done
  done
done
for norm in 0 1; do
  for s in $CTRL_SEEDS; do echo "code $norm $s 1" >> "$JOBS"; done
done
echo "$(wc -l < "$JOBS") job" | tee "$LOG/run.log"

run_one() {
  local ds=$1 norm=$2 s=$3 T=$4
  local f="$OUT/${ds}_T${T}_norm${norm}_s${s}.json"
  if [ "$SKIP_DONE" = "1" ] && [ -s "$f" ]; then
    echo "$(date -u +%FT%TZ) $ds T=$T norm=$norm s=$s bỏ qua (đã có) mã thoát 0"
    return 0
  fi
  NORMALIZE_ROWS=$norm $PY main_simulation_v2.py --dataset "$ds" --nodes "$NODES" \
      --nq "$NQ" --num-tables 5 --k-query 20 --meta-anchors 1 --multi-probe "$T" \
      --probe-bits 16 --use-pq --pq-variant m512 --seed "$s" --routing semantic \
      --out "$f" > "$LOG/${ds}_T${T}_norm${norm}_s${s}.log" 2>&1
  local rc=$?
  echo "$(date -u +%FT%TZ) $ds T=$T norm=$norm s=$s mã thoát $rc"
}
export -f run_one
export PY NODES NQ OUT LOG SKIP_DONE

xargs -P "$PARALLEL" -L 1 bash -c 'run_one "$@"' _ < "$JOBS" | tee -a "$LOG/run.log"

$PY ppna_r1/verify_norm.py --out "$OUT" --nq "$NQ" --seeds $SEEDS --ctrl-seeds $CTRL_SEEDS \
    | tee ppna_r1/verify_norm_report.txt
echo "XONG KIỂM CHUẨN HOÁ" | tee -a "$LOG/run.log"
