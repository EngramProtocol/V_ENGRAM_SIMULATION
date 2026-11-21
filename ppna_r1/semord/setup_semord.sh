#!/bin/bash
# Lấy và build artifact Semord của tác giả ở commit đã ghim, ngoài repo V-Engram.
#   SEMORD_ROOT (mặc định ~/semord_src): nơi clone LearnedHash và Vortex_system.
# Cần có sẵn: git, make, g++ có C++20 (GCC 10 trở lên), python3 có pip (venv của repo), truy cập
# GitHub và PyPI. Không cần sudo cho phần còn lại:
#   - không có cmake từ 3.16 thì cài cmake bằng pip vào $SEMORD_ROOT/tools/cmake;
#   - không có BLAS hoặc LAPACK của hệ thống thì build OpenBLAS (có LAPACK) vào $SEMORD_ROOT/openblas.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${SEMORD_ROOT:-$HOME/semord_src}"
LH_COMMIT=542528c8e88e1957a513cc7f086e713e69fb8905
VX_COMMIT=8766ddb579dd23a08b8b666c6fcd555bf2a23b3a
OB_TAG=v0.3.26      # cùng bản OpenBLAS với Ubuntu 24.04
JOBS="${JOBS:-$(nproc)}"
PY="${PY:-python3}"
case "$PY" in /*) ;; */*) PY="$PWD/$PY" ;; esac
# cmake cài bằng pip nằm ở đây; run_semord.sh cũng thêm thư mục này vào PATH cho các bước sau
export PATH="$ROOT/tools/cmake/cmake/data/bin:$PATH"
mkdir -p "$ROOT"

step() {   # step <log> <lệnh...>: chạy, lỗi thì in phần cuối log rồi dừng
  local log="$1"; shift
  if ! "$@" > "$log" 2>&1; then
    echo "LỖI ở bước: $*"; tail -25 "$log"; exit 1
  fi
}

miss=""
for c in git make g++ python3; do command -v "$c" > /dev/null || miss="$miss $c"; done
if [ -n "$miss" ]; then
  echo "Thiếu:$miss. Cài cần quyền sudo (hoặc nhờ người quản lý server): sudo apt-get install -y git build-essential python3"
  exit 1
fi
gv=$(g++ -dumpversion | cut -d. -f1)
if [ "$gv" -lt 10 ]; then
  echo "g++ bản $gv, nhưng Vortex_system cần C++20 (g++ 10 trở lên)."
  exit 1
fi
cmake_ok() {   # có cmake từ 3.16 trở lên
  command -v cmake > /dev/null || return 1
  local v
  v=$(cmake --version | head -1 | awk '{print $3}')
  [ "$(printf '%s\n3.16\n' "$v" | sort -V | head -1)" = "3.16" ]
}
if ! cmake_ok; then
  echo "Chưa có cmake từ 3.16: cài cmake bằng pip vào $ROOT/tools/cmake (không cần sudo)"
  step "$ROOT/cmake_pip.log" "$PY" -m pip install --upgrade --target "$ROOT/tools/cmake" "cmake>=3.16,<4"
  hash -r
  cmake_ok || { echo "Cài cmake bằng pip không được, xem $ROOT/cmake_pip.log"; exit 1; }
fi
echo "$(cmake --version | head -1) | g++ $(g++ -dumpversion)"

LDC=$(command -v ldconfig || echo /sbin/ldconfig)
blas=$("$LDC" -p 2> /dev/null | grep -E "libblas\.so|libopenblas\.so" | head -1 | awk '{print $NF}')
lapack=$("$LDC" -p 2> /dev/null | grep -E "liblapack\.so" | head -1 | awk '{print $NF}')
if [ -n "$blas" ] && [ -n "$lapack" ]; then
  mkdir -p "$ROOT/libs"
  # FindBLAS và FindLAPACK cần tên libblas.so và liblapack.so; máy chỉ có .so.3 thì tạo symlink riêng
  ln -sf "$blas" "$ROOT/libs/libblas.so"
  ln -sf "$lapack" "$ROOT/libs/liblapack.so"
  BLAS_ARGS=(-DCMAKE_LIBRARY_PATH="$ROOT/libs")
  echo "BLAS: $blas | LAPACK: $lapack"
else
  # Máy không có BLAS hoặc LAPACK: build OpenBLAS (BLAS và LAPACK trong một thư viện) vào
  # $ROOT/openblas, không cần sudo. C_LAPACK dùng bản LAPACK dịch sang C nên không cần Fortran.
  # Ghi rõ TARGET vì OpenBLAS tự nhận CPU hay lỗi trên máy ảo.
  if [ ! -f "$ROOT/openblas/lib/libopenblas.so" ]; then
    [ -d "$ROOT/OpenBLAS" ] || git clone -q --depth 1 -b "$OB_TAG" https://github.com/OpenMathLib/OpenBLAS.git "$ROOT/OpenBLAS"
    case "$(uname -m)" in
      x86_64) if grep -qw avx2 /proc/cpuinfo; then ob_target=HASWELL; else ob_target=GENERIC; fi ;;
      aarch64) ob_target=ARMV8 ;;
      *) ob_target=GENERIC ;;
    esac
    echo "Máy không có BLAS hoặc LAPACK: build OpenBLAS $OB_TAG (TARGET=$ob_target) vào $ROOT/openblas"
    step "$ROOT/openblas_build.log" make -C "$ROOT/OpenBLAS" -j"$JOBS" TARGET="$ob_target" \
      NOFORTRAN=1 C_LAPACK=1 USE_OPENMP=0 NO_STATIC=1
    step "$ROOT/openblas_install.log" make -C "$ROOT/OpenBLAS" PREFIX="$ROOT/openblas" NO_STATIC=1 install
  fi
  BLAS_ARGS=(-DCMAKE_LIBRARY_PATH="$ROOT/openblas/lib" -DBLA_VENDOR=OpenBLAS)
  echo "BLAS và LAPACK: $ROOT/openblas/lib/libopenblas.so ($OB_TAG)"
fi

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

step "$ROOT/lh_configure.log" cmake -S LearnedHash -B LearnedHash/build -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=OFF "${BLAS_ARGS[@]}"
step "$ROOT/lh_build.log" cmake --build LearnedHash/build -j"$JOBS" --target vortex_v1_cli vortex_model_selector
step "$ROOT/vx_configure.log" cmake -S Vortex_system -B Vortex_system/build -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=OFF -DVBENCH_ENABLE_CCACHE=OFF "${BLAS_ARGS[@]}"
echo "LearnedHash $(git -C LearnedHash rev-parse --short HEAD) | Vortex_system $(git -C Vortex_system rev-parse --short HEAD)"
ls -la LearnedHash/build/hash_functions_core/Vortex/vortex_v1_cli LearnedHash/build/hash_functions_core/Vortex/vortex_model_selector
echo "SETUP XONG"
