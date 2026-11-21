#!/bin/bash
# Dựng artifact Semord cho code và SciFact theo cách xác định (một luồng), rồi build vortex_bench.
#   LH=<LearnedHash> VX=<Vortex_system> DATA=<semord_data> WORK=<thư mục làm việc> NODES=1000 bash semord_pipeline.sh
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
mkdir -p "$VH"
for ds in code scifact; do
  [ -f "$VH/$ds.hnsw.index" ] || "$B/vortex_v1_cli" build_hnsw --dataset "$DATA/$ds/${ds}_base.fvecs" \
      --M 16 --efConstruction 100 --metric L2 --output "$VH/$ds.hnsw.index"
  if [ ! -f "$VH/${ds}_sel.json" ]; then
    ( cd "$VH" && "$B/vortex_model_selector" --dataset "$DATA/$ds/${ds}_base.fvecs" --index "$ds.hnsw.index" \
        --query "$DATA/$ds/${ds}_val_query.fvecs" --eval-k 5 --node-count-values "$NODES" \
        --seed "$SEL_SEED" --threads 1 --selector-parallelism 1 --max-search-seconds 3600 \
        --output "${ds}_sel.json" --disable-html-report > "${ds}_sel.log" 2>&1 )
  fi
  python3 -c "import json,sys; b=json.load(open('$VH/${ds}_sel.json'))['best']; print('$ds', b['config'])"
done
python3 "$(dirname "$0")/semord_artifacts.py" --lh "$LH" --vx "$VX" --data "$DATA" --sel-dir "$VH" --threads 1
cmake -S "$VX" -B "$VX/build" > "$WORK/vx_configure.log" 2>&1
grep -i "discovered" "$WORK/vx_configure.log" | cut -c1-80
cmake --build "$VX/build" -j"$(nproc)" --target vortex_bench > "$WORK/vx_build.log" 2>&1
"$VX/build/vortex_bench" --list-methods 2>&1 | grep -c "vortex_v1_" || true
echo "PIPELINE XONG"
