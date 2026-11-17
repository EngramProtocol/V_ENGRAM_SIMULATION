#!/bin/bash
# =============================================================================
# KIỂM CÁC VẤN ĐỀ MỤC 2.1–2.4 CỦA BẢN ĐÃ NỘP (ppna-r1-verify-s2)
#
# Nhóm A  đọc file kết quả có sẵn trên server, không chạy gì (vài giây):
#         2.1 số seed và nguồn gốc Bảng 4, 5, 8, 9; 2.2 tỉ lệ lookup chạm R_max
#         trong file Bảng 7; 2.4 log availability của Bảng 9 dựng trên overlay nào.
#         In ra ppna_r1/verify_s2_partA.txt ngay từ đầu.
# Nhóm B  2.1: chạy đủ 10 seed cho các hàng 5 seed (Bảng 5: T=1, T=12, K=10,
#         40, 80; Bảng 4: candidate threshold, hai corpus), code chưa chuẩn hoá
#         như bản đã nộp. Seed 20235956, 1..4 phải trùng từng số với file cũ.
# Nhóm C  2.2 và 2.3: mô hình iterative (k-bucket, join). Mỗi seed:
#           main      : cấu hình chính, mọi pha stable/all (so hồi quy với Bảng 7)
#           q_<X>     : join và ingest giữ stable/all, CHỈ truy vấn đổi sang X
#           b_<X>     : dựng mạng + ingest theo X ở mọi pha, đo vị trí record và
#                       bảng định tuyến, không chạy truy vấn (nhanh)
#         với X thuộc stable-topk, exhaust-all, exhaust-topk.
# Nhóm D  2.4: availability (main_churn_test.py) trên k-bucket có join và seed,
#         r = 1, 2, 3, mất 0/10/20/30% peer; thêm overlay ring để đối chiếu.
#
# Không đổi kết quả của bất kỳ thí nghiệm cũ nào: các cờ mới mặc định tắt, và
# đã kiểm code vá cho kết quả trùng từng bit với code cũ ở cấu hình mặc định.
#
#   PARALLEL=4 bash ppna_r1/run_verify_s2.sh
#   Chạy lại sau khi bị ngắt: cùng lệnh; job đã xong với cùng commit được bỏ qua.
#
# Tuỳ chọn (biến môi trường):
#   RUN_GROUPS="B C D"               nhóm cần chạy (A luôn chạy)
#   SEEDS_ITER="20235956 1 2 3 4" seed cho nhóm C
#   SEEDS_KB="20235956 1 ... 9"   seed cho nhóm D, overlay k-bucket (mặc định 10 seed)
#   SEEDS_RING="20235956 1 2"     seed cho nhóm D, overlay ring
#   RUN_SPLIT=1                  thêm job tách join/ingest cho exhaust-all, stable-topk
#   RUN_RMAX30=1                 thêm job exhaust-all chỉ ở truy vấn với R_max = 30
# =============================================================================
set -u
cd "$(dirname "$0")/.." || exit 1

PY=${PY:-python3}
PARALLEL=${PARALLEL:-4}
RUN_GROUPS=${RUN_GROUPS:-"B C D"}
SEEDS10="20235956 1 2 3 4 5 6 7 8 9"
SEEDS_ITER=${SEEDS_ITER:-"20235956 1 2 3 4"}
SEEDS_KB=${SEEDS_KB:-"20235956 1 2 3 4 5 6 7 8 9"}
SEEDS_RING=${SEEDS_RING:-"20235956 1 2"}
RUN_SPLIT=${RUN_SPLIT:-0}
RUN_RMAX30=${RUN_RMAX30:-0}
# Quy mô: mặc định là cấu hình của bài. Chỉ hạ khi chạy thử toàn bộ quy trình.
V2_NODES=${V2_NODES:-10000}; V2_NQ=${V2_NQ:-500}
IT_NODES=${IT_NODES:-10000}; IT_NQ=${IT_NQ:-500}; IT_FILES=${IT_FILES:-}
D_NODES=${D_NODES:-10000}; D_FILES=${D_FILES:-20000}; D_SAMPLE=${D_SAMPLE:-500}
OUT=${OUT:-ppna_r1/out_verify_s2}
LOG=${LOG:-ppna_r1/logs_verify_s2}
SNAP=ppna_r1/snap_existing
HEAD=$(git rev-parse --short HEAD)
mkdir -p "$OUT"/B "$OUT"/C "$OUT"/D "$LOG" "$SNAP" "$LOG"/smoke

# ---------------------------------------------------------------- kiểm đầu vào
for f in data/code_corpus_embeddings.npy data/code_query_embeddings.npy \
         data/code_pq_codes_m512.npy data/code_pq_codebook_m512.npy \
         data/code_ground_truth.json data/scifact_corpus_embeddings.npy \
         data/scifact_query_embeddings.npy data/scifact_pq_codes_m512.npy \
         data/scifact_pq_codebook_m512.npy data/scifact_ground_truth.json; do
  [ -f "$f" ] || { echo "THIẾU $f, dừng."; exit 1; }
done
$PY -c "import numpy, simpy" 2>/dev/null || { echo "THIẾU numpy/simpy: source venv/bin/activate"; exit 1; }

{
  echo "HEAD = $HEAD | tag = $(git describe --tags --always)"
  echo "file đã track bị sửa (phải trống):"
  git status --short | grep -v '^??' || true
  echo "nproc = $(nproc) | $(free -g | awk '/Mem/{print "RAM " $2 " GB, trống " $7 " GB"}')"
  echo "python = $($PY -c 'import sys, numpy, simpy; print(sys.version.split()[0], "numpy", numpy.__version__, "simpy", simpy.__version__)')"
  echo "RUN_GROUPS=$RUN_GROUPS | PARALLEL=$PARALLEL | SEEDS_ITER=$SEEDS_ITER | SEEDS_KB=$SEEDS_KB | SEEDS_RING=$SEEDS_RING | RUN_SPLIT=$RUN_SPLIT | RUN_RMAX30=$RUN_RMAX30"
  echo "quy mô: V2 $V2_NODES peer/$V2_NQ query | iterative $IT_NODES peer/$IT_NQ query${IT_FILES:+/$IT_FILES object} | availability $D_NODES peer/$D_SAMPLE object mẫu"
} > "$LOG/env.txt" 2>&1
cat "$LOG/env.txt"

# ---------------------------------------------------------------- nhóm A
# Chụp lại các file cũ dùng cho phân tích (giữ thời điểm ghi) để gửi kèm.
for pat in 'q5_termabl_*_s*.json' 'repl_r*_s*.json' 'fail_*_s*.json' 'failure_code_r*_s*.txt' \
           'result_code_N10000_L5_K20_MA1_T1_m512_s*_nq500.json' \
           'result_code_N10000_L5_K20_MA1_T12_m512_s*_nq500.json' \
           'result_code_N10000_L5_K10_MA1_T8_m512_s*_nq500.json' \
           'result_code_N10000_L5_K40_MA1_T8_m512_s*_nq500.json' \
           'result_code_N10000_L5_K80_MA1_T8_m512_s*_nq500.json' \
           'result_*_N10000_L5_K20_MA1_T8_m512_RANDCAND_s*_nq500.json' \
           'result_code_N10000_L5_K20_MA*_T8_m512_RANDOM_s*_nq500.json'; do
  for f in $pat */$pat; do
    [ -f "$f" ] || continue
    case "$f" in ppna_r1/*) continue ;; esac
    mkdir -p "$SNAP/$(dirname "$f")"
    cp -p "$f" "$SNAP/$f"
  done
done
ls -l --time-style=+%FT%T lsh10_*.txt */lsh10_*.txt 2>/dev/null > "$SNAP/lsh10_listing.txt" || true
echo "chụp $(find "$SNAP" -type f | wc -l) file cũ vào $SNAP"
$PY ppna_r1/verify_s2.py --parts A | tee ppna_r1/verify_s2_partA.txt

# ---------------------------------------------------------------- hàm chạy
ok_path() { echo "$1.ok"; }
done_ok() {   # $1 = file kết quả; đã xong với đúng commit?
  [ -s "$1" ] && [ -f "$1.ok" ] && [ "$(cat "$1.ok")" = "$HEAD" ]
}
finish() {    # $1 name, $2 file, $3 rc, $4 t0
  local name=$1 f=$2 rc=$3 t0=$4
  if [ "$rc" = "0" ] && [ -s "$f" ]; then echo "$HEAD" > "$f.ok"; fi
  echo "$(date -u +%FT%TZ) $name mã thoát $rc, $(( $(date +%s) - t0 )) giây"
}

ITER_BASE="SKIP_PAYLOAD=1 ROUTING_TABLE=kbucket BOOTSTRAP=join PQ_VARIANT=m512 SHARED_ORIGIN=1 NORMALIZE_ROWS=1 DIAG_BUILD=1 OVERLAP_STATS=0"
ITER_ARGS="--dataset code --nodes $IT_NODES --k-query 20 --multi-probe 8 --meta-anchors 1 --nq $IT_NQ${IT_FILES:+ --num-files $IT_FILES}"
FIX_BUILD="JOIN_STOP_RULE=stable JOIN_FRONTIER_SCOPE=all JOIN_R_MAX=15 INGEST_STOP_RULE=stable INGEST_FRONTIER_SCOPE=all INGEST_R_MAX=15"

run_job() {
  local g=$1; shift
  local t0; t0=$(date +%s)
  case "$g" in
  B)  # B <tên> <dataset> <T> <K> <routing> <seed>
      local name=$1 ds=$2 T=$3 K=$4 rt=$5 s=$6
      local f="$OUT/B/${name}_s${s}.json" extra=""
      done_ok "$f" && { echo "$(date -u +%FT%TZ) B/${name}_s${s} bỏ qua (đã có)"; return; }
      [ "$rt" = "randcand" ] && extra="--routing random_equalcand"
      NORMALIZE_ROWS=0 timeout 3600 $PY main_simulation_v2.py --dataset "$ds" --nodes "$V2_NODES" \
          --nq "$V2_NQ" --num-tables 5 --k-query "$K" --meta-anchors 1 --multi-probe "$T" \
          --probe-bits 16 --use-pq --pq-variant m512 --seed "$s" $extra --out "$f" \
          > "$LOG/B_${name}_s${s}.log" 2>&1
      finish "B/${name}_s${s}" "$f" $? "$t0" ;;
  C)  # C <kiểu: main|q|b|ji|q30> <biến thể: stable-all|stable-topk|exhaust-all|exhaust-topk> <seed>
      local kind=$1 var=$2 s=$3
      local sr=${var%-*} fs=${var#*-}
      local name="${kind}_${var}_s${s}" f="$OUT/C/${kind}_${var}_s${s}.json" envs=""
      done_ok "$f" && { echo "$(date -u +%FT%TZ) C/$name bỏ qua (đã có)"; return; }
      case "$kind" in
        main) envs="STOP_RULE=stable FRONTIER_SCOPE=all MEASURE_OVERLAP=1" ;;
        q)    envs="$FIX_BUILD STOP_RULE=$sr FRONTIER_SCOPE=$fs MEASURE_OVERLAP=1" ;;
        q30)  envs="$FIX_BUILD STOP_RULE=$sr FRONTIER_SCOPE=$fs R_MAX=30 MEASURE_OVERLAP=1" ;;
        ji)   envs="JOIN_STOP_RULE=stable JOIN_FRONTIER_SCOPE=all JOIN_R_MAX=15 STOP_RULE=$sr FRONTIER_SCOPE=$fs MEASURE_OVERLAP=1" ;;
        b)    envs="STOP_RULE=$sr FRONTIER_SCOPE=$fs BUILD_ONLY=1" ;;
      esac
      env $ITER_BASE $envs timeout 21600 $PY -u main_simulation.py $ITER_ARGS --seed "$s" \
          --out "$f" > "$LOG/C_${name}.log" 2>&1
      finish "C/$name" "$f" $? "$t0" ;;
  D)  # D <ring|kbucket> <r> <seed>
      local topo=$1 r=$2 s=$3
      local name="${topo}_r${r}_s${s}" f="$OUT/D/${topo}_r${r}_s${s}.json"
      done_ok "$f" && { echo "$(date -u +%FT%TZ) D/$name bỏ qua (đã có)"; return; }
      env DATASET=code NUM_NODES="$D_NODES" NUM_FILES="$D_FILES" RECOVERY_SAMPLE="$D_SAMPLE" \
          CHURN_STEPS=0,0.10,0.20,0.30 META_ANCHORS="$r" NET_SEED="$s" SAMPLE_SEED="$s" \
          INGEST_SAMPLE_ONLY=1 PQ_VARIANT=m512 ROUTING_TABLE="$topo" BOOTSTRAP=join \
          OUT_JSON="$f" timeout 21600 $PY -u main_churn_test.py > "$LOG/D_${name}.log" 2>&1
      finish "D/$name" "$f" $? "$t0" ;;
  esac
}
export -f run_job done_ok finish ok_path
export PY OUT LOG HEAD ITER_BASE ITER_ARGS FIX_BUILD V2_NODES V2_NQ D_NODES D_FILES D_SAMPLE

# ---------------------------------------------------------------- smoke test
# Bản thu nhỏ của mọi kiểu job, để lỗi lộ ra sau vài phút chứ không sau vài giờ.
echo "== smoke test =="
SM=$LOG/smoke
smoke_fail=0
NORMALIZE_ROWS=0 $PY main_simulation_v2.py --dataset scifact --nodes 2000 --nq 5 --num-tables 5 \
    --k-query 20 --meta-anchors 1 --multi-probe 8 --use-pq --pq-variant m512 --seed 1 \
    --routing random_equalcand --out "$SM/v2.json" > "$SM/v2.log" 2>&1 || smoke_fail=1
env $ITER_BASE $FIX_BUILD STOP_RULE=exhaust FRONTIER_SCOPE=all MEASURE_OVERLAP=1 \
    $PY main_simulation.py --dataset code --nodes 800 --num-files 1500 --k-query 20 \
    --multi-probe 8 --meta-anchors 1 --nq 3 --seed 1 --out "$SM/iter_q.json" > "$SM/iter_q.log" 2>&1 || smoke_fail=1
env $ITER_BASE STOP_RULE=exhaust FRONTIER_SCOPE=topk BUILD_ONLY=1 \
    $PY main_simulation.py --dataset code --nodes 800 --num-files 1500 --k-query 20 \
    --multi-probe 8 --meta-anchors 1 --nq 3 --seed 1 --out "$SM/iter_b.json" > "$SM/iter_b.log" 2>&1 || smoke_fail=1
env DATASET=code NUM_NODES=800 NUM_FILES=1500 RECOVERY_SAMPLE=10 CHURN_STEPS=0,0.30 \
    META_ANCHORS=2 NET_SEED=1 SAMPLE_SEED=1 INGEST_SAMPLE_ONLY=1 PQ_VARIANT=m512 \
    ROUTING_TABLE=kbucket BOOTSTRAP=join OUT_JSON="$SM/churn.json" \
    $PY main_churn_test.py > "$SM/churn.log" 2>&1 || smoke_fail=1
for f in v2 iter_q iter_b churn; do
  [ -s "$SM/$f.json" ] || { echo "  smoke $f: KHÔNG có kết quả, xem $SM/$f.log"; smoke_fail=1; }
done
if [ "$smoke_fail" != "0" ]; then echo "SMOKE TEST LỖI, dừng. Gửi thư mục $SM."; exit 1; fi
echo "  smoke test đạt"

# ---------------------------------------------------------------- danh sách job
JOBS="$LOG/jobs.txt"
: > "$JOBS"
case " $RUN_GROUPS " in *" C "*)
  for s in $SEEDS_ITER; do
    echo "C q exhaust-all $s" >> "$JOBS"
    echo "C main stable-all $s" >> "$JOBS"
    echo "C q exhaust-topk $s" >> "$JOBS"
    echo "C q stable-topk $s" >> "$JOBS"
    [ "$RUN_SPLIT" = "1" ] && { echo "C ji exhaust-all $s" >> "$JOBS"; echo "C ji stable-topk $s" >> "$JOBS"; }
    [ "$RUN_RMAX30" = "1" ] && echo "C q30 exhaust-all $s" >> "$JOBS"
  done
  for s in $SEEDS_ITER; do
    for v in exhaust-all exhaust-topk stable-topk; do echo "C b $v $s" >> "$JOBS"; done
  done ;;
esac
case " $RUN_GROUPS " in *" D "*)
  for s in $SEEDS_KB; do for r in 1 2 3; do echo "D kbucket $r $s" >> "$JOBS"; done; done
  for s in $SEEDS_RING; do for r in 1 2 3; do echo "D ring $r $s" >> "$JOBS"; done; done ;;
esac
case " $RUN_GROUPS " in *" B "*)
  for s in $SEEDS10; do
    echo "B code_T1_K20 code 1 20 sem $s" >> "$JOBS"
    echo "B code_T12_K20 code 12 20 sem $s" >> "$JOBS"
    echo "B code_T8_K10 code 8 10 sem $s" >> "$JOBS"
    echo "B code_T8_K40 code 8 40 sem $s" >> "$JOBS"
    echo "B code_T8_K80 code 8 80 sem $s" >> "$JOBS"
    echo "B code_randcand code 8 20 randcand $s" >> "$JOBS"
    echo "B scifact_randcand scifact 8 20 randcand $s" >> "$JOBS"
  done ;;
esac
echo "$(wc -l < "$JOBS") job, PARALLEL=$PARALLEL" | tee "$LOG/run.log"

xargs -P "$PARALLEL" -L 1 bash -c 'run_job "$@"' _ < "$JOBS" | tee -a "$LOG/run.log"

$PY ppna_r1/verify_s2.py --parts ABCD --out "$OUT" | tee ppna_r1/verify_s2_report.txt
echo "XONG KIỂM MỤC 2" | tee -a "$LOG/run.log"
