#!/bin/bash
# Lấy và build artifact Semord của tác giả ở commit đã ghim, ngoài repo V-Engram.
#   SEMORD_ROOT (mặc định ~/semord_src): nơi clone LearnedHash và Vortex_system.
# Cần: git, cmake >= 3.16, g++ có C++20 (GCC 10 trở lên), OpenMP, BLAS và LAPACK.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${SEMORD_ROOT:-$HOME/semord_src}"
LH_COMMIT=542528c8e88e1957a513cc7f086e713e69fb8905
VX_COMMIT=8766ddb579dd23a08b8b666c6fcd555bf2a23b3a
JOBS="${JOBS:-$(nproc)}"

miss=""
for c in git cmake g++ python3; do command -v "$c" > /dev/null || miss="$miss $c"; done
if [ -n "$miss" ]; then
  echo "Thiếu:$miss. Trên Ubuntu: sudo apt-get install -y git cmake g++ libopenblas-dev liblapack-dev"
  exit 1
fi
blas=$(ldconfig -p | grep -E "libblas\.so|libopenblas\.so" | head -1 | awk '{print $NF}')
lapack=$(ldconfig -p | grep -E "liblapack\.so" | head -1 | awk '{print $NF}')
if [ -z "$blas" ] || [ -z "$lapack" ]; then
  echo "Thiếu BLAS hoặc LAPACK. Trên Ubuntu: sudo apt-get install -y libopenblas-dev liblapack-dev"
  exit 1
fi
mkdir -p "$ROOT/libs"
# FindBLAS và FindLAPACK cần tên libblas.so và liblapack.so; máy chỉ có .so.3 thì tạo symlink riêng
ln -sf "$blas" "$ROOT/libs/libblas.so"
ln -sf "$lapack" "$ROOT/libs/liblapack.so"

cd "$ROOT"
[ -d LearnedHash ] || git clone -q https://github.com/ShengzeWang/LearnedHash.git
[ -d Vortex_system ] || git clone -q https://github.com/ShengzeWang/Vortex_system.git
git -C LearnedHash checkout -q "$LH_COMMIT"
git -C Vortex_system checkout -q "$VX_COMMIT"
# Sửa duy nhất để build trên Linux: uint64_t là unsigned long nên literal 0ULL gọi constructor
# ModelInput bị mơ hồ (tác giả build trên macOS). Không đổi logic.
if git -C LearnedHash apply --check "$HERE/learnedhash_linux.patch" 2> /dev/null; then
  git -C LearnedHash apply "$HERE/learnedhash_linux.patch"
fi
# Bỏ các artifact VortexHash của tác giả cho dữ liệu khác (SIFT, GIST, ...) khỏi lần build để rút
# ngắn thời gian; artifact cho code và SciFact sinh ở bước sau.
mkdir -p "$ROOT/vortex_unused_methods"
for d in Vortex_system/methods/vortex_v1_*; do
  [ -d "$d" ] || continue
  # giữ artifact siftsmall (nhỏ): CMake của Vortex_system cần ít nhất một artifact khi configure
  case "$(basename "$d")" in vortex_v1_code_s*|vortex_v1_scifact_s*|vortex_v1_siftsmall) ;; *) mv "$d" "$ROOT/vortex_unused_methods/" ;; esac
done

step() {   # step <log> <lệnh...>: chạy, lỗi thì in phần cuối log rồi dừng
  local log="$1"; shift
  if ! "$@" > "$log" 2>&1; then
    echo "LỖI ở bước: $*"; tail -25 "$log"; exit 1
  fi
}
step "$ROOT/lh_configure.log" cmake -S LearnedHash -B LearnedHash/build -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=OFF -DCMAKE_LIBRARY_PATH="$ROOT/libs"
step "$ROOT/lh_build.log" cmake --build LearnedHash/build -j"$JOBS" --target vortex_v1_cli vortex_model_selector
step "$ROOT/vx_configure.log" cmake -S Vortex_system -B Vortex_system/build -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=OFF -DVBENCH_ENABLE_CCACHE=OFF -DCMAKE_LIBRARY_PATH="$ROOT/libs"
echo "LearnedHash $(git -C LearnedHash rev-parse --short HEAD) | Vortex_system $(git -C Vortex_system rev-parse --short HEAD)"
ls -la LearnedHash/build/hash_functions_core/Vortex/vortex_v1_cli LearnedHash/build/hash_functions_core/Vortex/vortex_model_selector
echo "SETUP XONG"
