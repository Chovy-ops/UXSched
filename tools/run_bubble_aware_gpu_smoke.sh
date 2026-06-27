#!/usr/bin/env bash
set -u

ROOT="/home/zm/project/UXSched"
OUT_DIR=""
BUILD_DIR="${ROOT}/build-cutlass-cu128"
UXSCHED_BUILD="${ROOT}/build-hb-cu128"
CUTLASS_ROOT_VALUE="${CUTLASS_ROOT:-/home/zm/project/cutlass}"
CUDA_HOME_VALUE="${CUDA_HOME:-/usr/local/cuda-12.8}"
CUDA_COMPILER_VALUE="${CUDACXX:-/usr/local/cuda-12.8/bin/nvcc}"
CUDA_LIB="${XSCHED_CUDA_LIB:-/usr/lib/wsl/lib/libcuda.so.1}"
M=2048
N=2048
K=2048
SPLIT_BLOCKS=52
STREAM_MODE="explicit"
TIMEOUT_SEC=30
BUILD_PROBE=0
VERIFIED_KERNEL_FILE="${ROOT}/benchmarks/cutlass/verified_kernel_sm120_fp32_simt.txt"
VERIFIED_KERNELS=""
XSERVER_PID=""

usage() {
  printf 'Usage: %s --output-dir DIR [--build-probe] [--build-dir DIR] [--uxsched-build DIR] [--m N] [--n N] [--k N] [--split-blocks N] [--timeout-sec N] [--verified-kernel-file PATH]\n' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) OUT_DIR="$2"; shift 2 ;;
    --build-probe) BUILD_PROBE=1; shift ;;
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    --uxsched-build) UXSCHED_BUILD="$2"; shift 2 ;;
    --cutlass-root) CUTLASS_ROOT_VALUE="$2"; shift 2 ;;
    --cuda-home) CUDA_HOME_VALUE="$2"; shift 2 ;;
    --cuda-compiler) CUDA_COMPILER_VALUE="$2"; shift 2 ;;
    --cuda-lib) CUDA_LIB="$2"; shift 2 ;;
    --m) M="$2"; shift 2 ;;
    --n) N="$2"; shift 2 ;;
    --k) K="$2"; shift 2 ;;
    --split-blocks) SPLIT_BLOCKS="$2"; shift 2 ;;
    --stream) STREAM_MODE="$2"; shift 2 ;;
    --timeout-sec) TIMEOUT_SEC="$2"; shift 2 ;;
    --verified-kernel-file) VERIFIED_KERNEL_FILE="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${OUT_DIR}" ]]; then
  printf 'missing required --output-dir\n' >&2
  usage >&2
  exit 2
fi

PROBE="${BUILD_DIR}/cutlass_launch_probe"
HB_SHIM="${UXSCHED_BUILD}/platforms/cuda/libshimcuda.so"
XSERVER="${UXSCHED_BUILD}/service/xserver"
HB_LIB_PATH="${UXSCHED_BUILD}/platforms/cuda:${UXSCHED_BUILD}/preempt:/usr/lib/wsl/lib"

mkdir -p "${OUT_DIR}"

quote_command() {
  local first=1
  for arg in "$@"; do
    if [[ "${first}" -eq 0 ]]; then printf ' '; fi
    printf '%q' "$arg"
    first=0
  done
  printf '\n'
}

load_verified_kernel() {
  if [[ ! -f "${VERIFIED_KERNEL_FILE}" ]]; then
    printf 'verified kernel file unavailable: %s\n' "${VERIFIED_KERNEL_FILE}" >&2
    return 1
  fi
  VERIFIED_KERNELS="$(grep -vE '^[[:space:]]*(#|$)' "${VERIFIED_KERNEL_FILE}" | head -n 1)"
  if [[ -z "${VERIFIED_KERNELS}" || "${VERIFIED_KERNELS}" == "*" ]]; then
    printf 'verified kernel allowlist must be non-empty and not wildcard\n' >&2
    return 1
  fi
}

write_metadata() {
  {
    printf 'ROOT=%s\n' "${ROOT}"
    printf 'GIT_HEAD=%s\n' "$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || true)"
    printf 'CUTLASS_ROOT=%s\n' "${CUTLASS_ROOT_VALUE}"
    printf 'CUTLASS_REVISION=%s\n' "$(git -C "${CUTLASS_ROOT_VALUE}" rev-parse --short HEAD 2>/dev/null || true)"
    printf 'CUDA_HOME=%s\n' "${CUDA_HOME_VALUE}"
    printf 'CUDACXX=%s\n' "${CUDA_COMPILER_VALUE}"
    printf 'XSCHED_CUDA_LIB=%s\n' "${CUDA_LIB}"
    printf 'CUXTRA_CUDA_LIB=%s\n' "${CUDA_LIB}"
    printf 'PROBE=%s\n' "${PROBE}"
    printf 'HB_SHIM=%s\n' "${HB_SHIM}"
    printf 'XSERVER=%s\n' "${XSERVER}"
    printf 'M=%s\nN=%s\nK=%s\n' "${M}" "${N}" "${K}"
    printf 'SPLIT_BLOCKS=%s\n' "${SPLIT_BLOCKS}"
    printf 'STREAM_MODE=%s\n' "${STREAM_MODE}"
    printf 'TIMEOUT_SEC=%s\n' "${TIMEOUT_SEC}"
    printf 'UXSCHED_BUBBLE_HINT_MODE=explicit\n'
  } > "${OUT_DIR}/metadata.env"
}

build_probe_if_requested() {
  if [[ "${BUILD_PROBE}" -eq 0 ]]; then return 0; fi
  local dir="${OUT_DIR}/build_cutlass_launch_probe"
  mkdir -p "${dir}"
  quote_command "${ROOT}/tools/build_cutlass_launch_probe.sh" \
    --build-dir "${BUILD_DIR}" \
    --cutlass-root "${CUTLASS_ROOT_VALUE}" \
    --cuda-home "${CUDA_HOME_VALUE}" \
    --cuda-compiler "${CUDA_COMPILER_VALUE}" > "${dir}/command.txt"
  "${ROOT}/tools/build_cutlass_launch_probe.sh" \
    --build-dir "${BUILD_DIR}" \
    --cutlass-root "${CUTLASS_ROOT_VALUE}" \
    --cuda-home "${CUDA_HOME_VALUE}" \
    --cuda-compiler "${CUDA_COMPILER_VALUE}" \
    > "${dir}/stdout.log" 2> "${dir}/stderr.log"
}

start_xserver() {
  local dir="${OUT_DIR}/xserver"
  mkdir -p "${dir}"
  quote_command env -u LD_PRELOAD -u XSCHED_POLICY "${XSERVER}" HPF 50000 > "${dir}/command.txt"
  env -u LD_PRELOAD -u XSCHED_POLICY "${XSERVER}" HPF 50000 \
    > "${dir}/stdout.log" 2> "${dir}/stderr.log" &
  XSERVER_PID=$!
  printf '%s\n' "${XSERVER_PID}" > "${dir}/pid.txt"
  sleep 1
}

stop_xserver() {
  if [[ -n "${XSERVER_PID}" ]] && kill -0 "${XSERVER_PID}" 2>/dev/null; then
    kill "${XSERVER_PID}" 2>/dev/null || true
    wait "${XSERVER_PID}" 2>/dev/null || true
  fi
}

trap stop_xserver EXIT

write_case_env() {
  local file="$1"
  local bubble="$2"
  {
    printf 'CUDA_HOME=%s\n' "${CUDA_HOME_VALUE}"
    printf 'XSCHED_CUDA_LIB=%s\n' "${CUDA_LIB}"
    printf 'CUXTRA_CUDA_LIB=%s\n' "${CUDA_LIB}"
    printf 'LD_PRELOAD=%s\n' "${HB_SHIM}"
    printf 'LD_LIBRARY_PATH_CASE=%s\n' "${HB_LIB_PATH}"
    printf 'XSCHED_SCHEDULER=GLB\n'
    printf 'XSCHED_AUTO_XQUEUE=ON\n'
    printf 'XSCHED_AUTO_XQUEUE_LEVEL=1\n'
    printf 'XSCHED_AUTO_XQUEUE_PRIORITY=-10\n'
    printf 'UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED\n'
    printf 'UXSCHED_HB_SPLIT_BLOCKS=%s\n' "${SPLIT_BLOCKS}"
    printf 'UXSCHED_HB_VERIFIED_KERNELS=%s\n' "${VERIFIED_KERNELS}"
    printf 'UXSCHED_BUBBLE_AWARE=%s\n' "${bubble}"
    printf 'UXSCHED_BUBBLE_MAX_IN_FLIGHT=1\n'
    printf 'UXSCHED_BUBBLE_FAIL_SAFE=ON\n'
    printf 'UXSCHED_BUBBLE_LOG=ON\n'
  } > "${file}"
}

run_case() {
  local case_name="$1"
  local bubble="$2"
  local smoke="$3"
  local dir="${OUT_DIR}/${case_name}"
  mkdir -p "${dir}"
  local output_jsonl="${dir}/output.jsonl"
  : > "${output_jsonl}"
  write_case_env "${dir}/environment_snapshot.txt" "${bubble}"

  local cmd=("${PROBE}" --mode runtime --m "${M}" --n "${N}" --k "${K}" \
    --iterations 1 --warmup 0 --stream "${STREAM_MODE}" --correctness \
    --output "${output_jsonl}" --bubble-smoke "${smoke}")
  quote_command "${cmd[@]}" > "${dir}/command.txt"

  (
    export CUDA_HOME="${CUDA_HOME_VALUE}"
    export PATH="${CUDA_HOME_VALUE}/bin:${PATH}"
    export LD_PRELOAD="${HB_SHIM}"
    export LD_LIBRARY_PATH="${HB_LIB_PATH}:${LD_LIBRARY_PATH:-}"
    export XSCHED_CUDA_LIB="${CUDA_LIB}"
    export CUXTRA_CUDA_LIB="${CUDA_LIB}"
    export XSCHED_SCHEDULER=GLB
    export XSCHED_AUTO_XQUEUE=ON
    export XSCHED_AUTO_XQUEUE_LEVEL=1
    export XSCHED_AUTO_XQUEUE_PRIORITY=-10
    export UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED
    export UXSCHED_CUDART_TRACE=1
    export UXSCHED_XQUEUE_TRACE=1
    export UXSCHED_HB_STRICT=0
    export UXSCHED_HB_SPLIT_BLOCKS="${SPLIT_BLOCKS}"
    export UXSCHED_HB_VERIFIED_KERNELS="${VERIFIED_KERNELS}"
    export UXSCHED_BUBBLE_AWARE="${bubble}"
    export UXSCHED_BUBBLE_MAX_IN_FLIGHT=1
    export UXSCHED_BUBBLE_FAIL_SAFE=ON
    export UXSCHED_BUBBLE_LOG=ON
    timeout "${TIMEOUT_SEC}" "${cmd[@]}"
  ) > "${dir}/stdout.log" 2> "${dir}/stderr.log"
  local rc=$?
  {
    printf 'return_code=%s\n' "${rc}"
    if [[ "${rc}" -eq 0 ]]; then
      printf 'status=COMPLETE\n'
    elif [[ "${rc}" -eq 124 ]]; then
      printf 'status=TIMEOUT\n'
    else
      printf 'status=FAILED\n'
    fi
  } > "${dir}/status.env"
}

load_verified_kernel || exit 2
write_metadata
build_probe_if_requested || exit $?

if [[ ! -x "${PROBE}" ]]; then
  printf 'probe unavailable: %s\n' "${PROBE}" >&2
  exit 2
fi
if [[ ! -f "${HB_SHIM}" ]]; then
  printf 'shim unavailable: %s\n' "${HB_SHIM}" >&2
  exit 2
fi

start_xserver
run_case case_off OFF none
run_case case_explicit_open ON explicit-open
run_case case_hp_active ON hp-active
run_case case_no_hint ON no-hint
run_case case_fail_safe ON fail-safe

python3 "${ROOT}/tools/check_bubble_aware_gpu_smoke.py" --result-dir "${OUT_DIR}"
