#!/bin/bash
# Dựng artifact Semord cho code và SciFact theo cách xác định (một luồng), rồi build vortex_bench.
#   LH=<LearnedHash> VX=<Vortex_system> DATA=<semord_data> WORK=<thư mục làm việc> NODES=1000 bash semord_pipeline.sh
# NODES là số node overlay mà bộ chọn cấu hình VHash nhắm tới (1000 hoặc 2000).
# Mọi bước chạy với OMP_NUM_THREADS=1: dựng HNSW bằng nhiều luồng cho đồ thị khác nhau giữa các lần
# chạy (đã kiểm), nên skeleton và model VHash cũng khác.
set -eu
: "${LH:?}" "${VX:?}" "${DATA:?}" "${WORK:?}"
NODES="${NODES:-1000}"
SEL_SEED="${SEL_SEED:-20235956}"
export OMP_NUM_THREADS=1
export VORTEX_ROOT="$LH"
B="$LH/build/hash_functions_core/Vortex"
VH="$WORK/vh_n$NODES"
PIN="$(cd "$(dirname "$0")" && pwd)/sel"
# N = 1.000: cấu hình cố định sel/<ds>_sel.json, model vortex_v1_<ds>_s<seed>. N khác: sel/<ds>_sel_n<N>.json,
# model vortex_v1_<ds>_n<N>_s<seed>, để các bộ model của từng N nằm cạnh nhau trong vortex_bench.
if [ "$NODES" = 1000 ]; then SUF=""; else SUF="_n$NODES"; fi
mkdir -p "$VH"
for ds in code scifact; do
  [ -f "$VH/$ds.hnsw.index" ] || "$B/vortex_v1_cli" build_hnsw --dataset "$DATA/$ds/${ds}_base.fvecs" \
      --M 16 --efConstruction 100 --metric L2 --output "$VH/$ds.hnsw.index"
  # Cấu hình VHash cố định (sel/*.json): bộ chọn chấm điểm có cả thời gian đo được nên chạy lại có thể
  # chọn khác. SEMORD_RESELECT=1 thì bỏ cấu hình cố định và chạy lại bộ chọn.
  PINF="$PIN/${ds}_sel${SUF}.json"
  if [ "${SEMORD_RESELECT:-0}" != 1 ] && [ -f "$PINF" ]; then
    cp "$PINF" "$VH/${ds}_sel.json"
    echo "$ds: dùng cấu hình VHash cố định trong $PINF"
  fi
  if [ ! -f "$VH/${ds}_sel.json" ]; then
    ( cd "$VH" && "$B/vortex_model_selector" --dataset "$DATA/$ds/${ds}_base.fvecs" --index "$ds.hnsw.index" \
        --query "$DATA/$ds/${ds}_val_query.fvecs" --eval-k 5 --node-count-values "$NODES" \
        --seed "$SEL_SEED" --threads 1 --selector-parallelism 1 --max-search-seconds 3600 \
        --output "${ds}_sel.json" --disable-html-report > "${ds}_sel.log" 2>&1 )
  fi
  python3 -c "import json,sys; b=json.load(open('$VH/${ds}_sel.json'))['best']; print('$ds', b['config'])"
done
python3 "$(dirname "$0")/semord_artifacts.py" --lh "$LH" --vx "$VX" --data "$DATA" --sel-dir "$VH" --threads 1 \
    --suffix "$SUF"
cmake -S "$VX" -B "$VX/build" > "$WORK/vx_configure.log" 2>&1
grep -i "discovered" "$WORK/vx_configure.log" | cut -c1-80
cmake --build "$VX/build" -j"$(nproc)" --target vortex_bench > "$WORK/vx_build.log" 2>&1
"$VX/build/vortex_bench" --list-methods 2>&1 | grep -c "vortex_v1_" || true
echo "PIPELINE XONG"
