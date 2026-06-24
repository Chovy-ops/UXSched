#!/usr/bin/env bash
set -u

ROOT="/home/zm/project/UXSched"
HB_REPO="/home/zm/project/hummingbird"
HB_BUILD="/home/zm/project/hummingbird/build-lite"
CUDA_LIB="/usr/lib/wsl/lib/libcuda.so.1"
OUT_DIR=""

usage() {
  printf 'Usage: %s --output-dir PATH [--cuda-lib PATH]\n' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --cuda-lib)
      CUDA_LIB="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${OUT_DIR}" ]]; then
  printf 'missing required --output-dir\n' >&2
  usage >&2
  exit 2
fi

BENCH="${HB_BUILD}/benchmarks/hb_open_resnet_like_eval"
RUNTIME_BENCH="${HB_BUILD}/benchmarks/hb_open_resnet_like_runtime_eval"
HB_SHIM="${ROOT}/build-hb/platforms/cuda/libshimcuda.so"
XSERVER="${ROOT}/build-hb/service/xserver"
HB_LIB_PATH="${ROOT}/build-hb/platforms/cuda:${ROOT}/build-hb/preempt:/usr/lib/wsl/lib"
VERIFIED_KERNELS="hb_open_resnet_conv2d_kernel,hb_open_resnet_relu_kernel,hb_open_resnet_residual_add_kernel,hb_open_resnet_checksum_kernel"
XSERVER_PID=""

mkdir -p "${OUT_DIR}"

quote_command() {
  local first=1
  for arg in "$@"; do
    if [[ "${first}" -eq 0 ]]; then
      printf ' '
    fi
    printf '%q' "${arg}"
    first=0
  done
  printf '\n'
}

write_common_env() {
  local file="$1"
  {
    printf 'ROOT=%s\n' "${ROOT}"
    printf 'HB_REPO=%s\n' "${HB_REPO}"
    printf 'HB_BUILD=%s\n' "${HB_BUILD}"
    printf 'BENCH=%s\n' "${BENCH}"
    printf 'RUNTIME_BENCH=%s\n' "${RUNTIME_BENCH}"
    printf 'HB_SHIM=%s\n' "${HB_SHIM}"
    printf 'XSERVER=%s\n' "${XSERVER}"
    printf 'CUDA_LIB=%s\n' "${CUDA_LIB}"
    printf 'LD_LIBRARY_PATH_BASE=%s\n' "${HB_LIB_PATH}"
    printf 'VERIFIED_KERNELS=%s\n' "${VERIFIED_KERNELS}"
  } > "${file}"
}

start_xserver() {
  local dir="${OUT_DIR}/xserver"
  mkdir -p "${dir}"
  write_common_env "${dir}/env.txt"
  quote_command env -u LD_PRELOAD -u XSCHED_POLICY "${XSERVER}" HPF 50000 > "${dir}/command.txt"
  env -u LD_PRELOAD -u XSCHED_POLICY "${XSERVER}" HPF 50000 \
    > "${dir}/stdout.log" 2> "${dir}/stderr.log" &
  XSERVER_PID=$!
  printf '%s\n' "${XSERVER_PID}" > "${dir}/pid.txt"
  sleep 1
  if kill -0 "${XSERVER_PID}" 2>/dev/null; then
    printf 'status=RUNNING\n' > "${dir}/status.txt"
  else
    printf 'status=FAILED_TO_START\n' > "${dir}/status.txt"
  fi
}

stop_xserver() {
  if [[ -n "${XSERVER_PID}" ]] && kill -0 "${XSERVER_PID}" 2>/dev/null; then
    kill "${XSERVER_PID}" 2>/dev/null || true
    wait "${XSERVER_PID}" 2>/dev/null || true
    printf 'status=STOPPED\n' > "${OUT_DIR}/xserver/status.txt"
  fi
}

trap stop_xserver EXIT

write_case_status() {
  local dir="$1"
  local rc="$2"
  local jsonl="$3"
  {
    printf 'return_code=%s\n' "${rc}"
    if [[ -f "${jsonl}" ]] && grep -q '"cuda_available":false' "${jsonl}"; then
      printf 'status=BLOCKED\n'
      printf 'reason=CUDA_UNAVAILABLE\n'
    elif [[ "${rc}" -eq 0 ]]; then
      printf 'status=RAN\n'
    else
      printf 'status=FAILED\n'
    fi
  } > "${dir}/status.txt"
}

extract_evidence() {
  local dir="$1"
  local jsonl="$2"
  if [[ -f "${jsonl}" ]]; then
    grep -o '"checksum":[^,}]*' "${jsonl}" > "${dir}/checksum.txt" || true
  fi
  if [[ ! -s "${dir}/checksum.txt" ]]; then
    printf 'NO_CHECKSUM_OBSERVED\n' > "${dir}/checksum.txt"
  fi

  grep -hE '\[UXSCHED-HB\].*(split_count|backend_selected=HB_SPLIT|transform_succeeded|split_group_completed|lp_in_flight_threshold|HIGH_PRIORITY_PASSTHROUGH|fallback=NATIVE)' \
    "${dir}/stdout.log" "${dir}/stderr.log" > "${dir}/split_trace.log" || true
  if [[ ! -s "${dir}/split_trace.log" ]]; then
    printf 'NO_SPLIT_TRACE_OBSERVED\n' > "${dir}/split_trace.log"
  fi

  grep -hE '\[UXSCHED-HB\].*(transform_succeeded|backend_selected=HB_SPLIT|capability=splittable|split_count)' \
    "${dir}/stdout.log" "${dir}/stderr.log" > "${dir}/transformed_launch_evidence.log" || true
  if [[ ! -s "${dir}/transformed_launch_evidence.log" ]]; then
    printf 'NO_TRANSFORMED_LAUNCH_OBSERVED\n' > "${dir}/transformed_launch_evidence.log"
  fi

  grep -hE '\[UXSCHED-HB\].*split_group_completed' \
    "${dir}/stdout.log" "${dir}/stderr.log" > "${dir}/child_completion.log" || true
  if [[ ! -s "${dir}/child_completion.log" ]]; then
    printf 'NO_CHILD_COMPLETION_OBSERVED\n' > "${dir}/child_completion.log"
  fi

  grep -hE 'hb_open_resnet_like.*wrote|LP-only correctness|split correctness oracle|no CUDA device' \
    "${dir}/stdout.log" "${dir}/stderr.log" > "${dir}/parent_completion.log" || true
  if [[ ! -s "${dir}/parent_completion.log" ]]; then
    printf 'NO_PARENT_COMPLETION_OBSERVED\n' > "${dir}/parent_completion.log"
  fi
}

run_case() {
  local name="$1"
  shift
  local dir="${OUT_DIR}/${name}"
  local jsonl="${dir}/output.jsonl"
  local rc=0
  mkdir -p "${dir}"
  write_common_env "${dir}/env.txt"
  {
    printf 'CASE=%s\n' "${name}"
    printf 'OUTPUT_JSONL=%s\n' "${jsonl}"
  } >> "${dir}/env.txt"
  quote_command "$@" --output "${jsonl}" > "${dir}/command.txt"
  "$@" --output "${jsonl}" > "${dir}/stdout.log" 2> "${dir}/stderr.log" || rc=$?
  printf '%s\n' "${rc}" > "${dir}/return_code.txt"
  write_case_status "${dir}" "${rc}" "${jsonl}"
  extract_evidence "${dir}" "${jsonl}"
  return 0
}

COMMON_ARGS=(
  --batch-size 8
  --channels 16
  --height 56
  --width 56
  --num-blocks 4
  --warmup 0
)

run_case "native_open_resnet_like_lp" \
  env -u LD_PRELOAD -u XSCHED_POLICY -u HB_TASK_PRIORITY \
    XSCHED_CUDA_LIB="${CUDA_LIB}" \
    CUXTRA_CUDA_LIB="${CUDA_LIB}" \
    "${BENCH}" "${COMMON_ARGS[@]}" --role lp --duration-ms 0 --iterations 1

start_xserver

run_case "uxsched_native_lp" \
  env -u XSCHED_POLICY -u HB_TASK_PRIORITY \
    LD_LIBRARY_PATH="${HB_LIB_PATH}" \
    LD_PRELOAD="${HB_SHIM}" \
    XSCHED_CUDA_LIB="${CUDA_LIB}" \
    CUXTRA_CUDA_LIB="${CUDA_LIB}" \
    XSCHED_SCHEDULER=GLB \
    XSCHED_AUTO_XQUEUE=ON \
    XSCHED_AUTO_XQUEUE_LEVEL=1 \
    XSCHED_AUTO_XQUEUE_PRIORITY=-10 \
    UXSCHED_CUDA_RUNTIME_STRATEGY=NATIVE \
    "${BENCH}" "${COMMON_ARGS[@]}" --role lp --duration-ms 0 --iterations 1

run_case "uxsched_hb_fixed_lp" \
  env -u XSCHED_POLICY -u HB_TASK_PRIORITY \
    LD_LIBRARY_PATH="${HB_LIB_PATH}" \
    LD_PRELOAD="${HB_SHIM}" \
    XSCHED_CUDA_LIB="${CUDA_LIB}" \
    CUXTRA_CUDA_LIB="${CUDA_LIB}" \
    XSCHED_SCHEDULER=GLB \
    XSCHED_AUTO_XQUEUE=ON \
    XSCHED_AUTO_XQUEUE_LEVEL=1 \
    XSCHED_AUTO_XQUEUE_PRIORITY=-10 \
    UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED \
    UXSCHED_HB_SPLIT_BLOCKS=512 \
    UXSCHED_HB_STRICT=0 \
    UXSCHED_HB_VERIFIED_KERNELS="${VERIFIED_KERNELS}" \
    "${BENCH}" "${COMMON_ARGS[@]}" --role lp --duration-ms 0 --iterations 1

run_case "uxsched_hb_fixed_hp_passthrough" \
  env -u XSCHED_POLICY -u HB_TASK_PRIORITY \
    LD_LIBRARY_PATH="${HB_LIB_PATH}" \
    LD_PRELOAD="${HB_SHIM}" \
    XSCHED_CUDA_LIB="${CUDA_LIB}" \
    CUXTRA_CUDA_LIB="${CUDA_LIB}" \
    XSCHED_SCHEDULER=GLB \
    XSCHED_AUTO_XQUEUE=ON \
    XSCHED_AUTO_XQUEUE_LEVEL=1 \
    XSCHED_AUTO_XQUEUE_PRIORITY=10 \
    UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED \
    UXSCHED_HB_SPLIT_BLOCKS=512 \
    UXSCHED_HB_STRICT=0 \
    UXSCHED_HB_VERIFIED_KERNELS="${VERIFIED_KERNELS}" \
    "${BENCH}" "${COMMON_ARGS[@]}" --role hp --requests 1 --period-us 1000

run_case "uxsched_hb_fixed_fallback_unverified" \
  env -u XSCHED_POLICY -u HB_TASK_PRIORITY \
    LD_LIBRARY_PATH="${HB_LIB_PATH}" \
    LD_PRELOAD="${HB_SHIM}" \
    XSCHED_CUDA_LIB="${CUDA_LIB}" \
    CUXTRA_CUDA_LIB="${CUDA_LIB}" \
    XSCHED_SCHEDULER=GLB \
    XSCHED_AUTO_XQUEUE=ON \
    XSCHED_AUTO_XQUEUE_LEVEL=1 \
    XSCHED_AUTO_XQUEUE_PRIORITY=-10 \
    UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED \
    UXSCHED_HB_SPLIT_BLOCKS=512 \
    UXSCHED_HB_STRICT=0 \
    UXSCHED_HB_VERIFIED_KERNELS=__not_verified__ \
    "${BENCH}" "${COMMON_ARGS[@]}" --role lp --duration-ms 0 --iterations 1

run_case "sync_event_boundary_probe" \
  env -u XSCHED_POLICY -u HB_TASK_PRIORITY \
    LD_LIBRARY_PATH="${HB_LIB_PATH}" \
    LD_PRELOAD="${HB_SHIM}" \
    XSCHED_CUDA_LIB="${CUDA_LIB}" \
    CUXTRA_CUDA_LIB="${CUDA_LIB}" \
    XSCHED_SCHEDULER=GLB \
    XSCHED_AUTO_XQUEUE=ON \
    XSCHED_AUTO_XQUEUE_LEVEL=1 \
    XSCHED_AUTO_XQUEUE_PRIORITY=-10 \
    UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED \
    UXSCHED_HB_SPLIT_BLOCKS=512 \
    UXSCHED_HB_STRICT=0 \
    UXSCHED_HB_VERIFIED_KERNELS="${VERIFIED_KERNELS}" \
    "${RUNTIME_BENCH}" "${COMMON_ARGS[@]}" --role lp --duration-ms 0 --iterations 1 \
    --correctness-mode lp-only --correctness-iterations 1 --lp-correctness-sync-boundary event

printf 'Gate 1 smoke artifacts: %s\n' "${OUT_DIR}"
