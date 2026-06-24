# HB Runtime Integration Status

Allowed status values in this file:

- IMPLEMENTED
- COMPILE VERIFIED
- RUNTIME VERIFIED
- CORRECTNESS VERIFIED
- PERFORMANCE VERIFIED
- NOT TESTED
- BLOCKED
- FAILED

## Current Runtime Strategy Status

| Item | Status | Notes |
| --- | --- | --- |
| Branch `feature/hummingbird-split-backend` | IMPLEMENTED | Continuing from `4146c1e`. |
| Re-audit document | IMPLEMENTED | `docs/hummingbird_runtime_reaudit.md`. |
| `CudaRuntimeStrategy` interface | COMPILE VERIFIED | Added under CUDA HAL runtime directory. |
| `NativeRuntimeStrategy` | COMPILE VERIFIED | Preserves original `CudaKernelLaunchCommand` path. |
| `HummingbirdRuntimeStrategy` | COMPILE VERIFIED | `HB_FIXED` delegates to fixed split implementation. |
| `UXSCHED_CUDA_RUNTIME_STRATEGY=NATIVE` | COMPILE VERIFIED | Runtime tests not run. |
| `UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED` | FAILED | Manual GPU Gate 1 reached PTX transform but fell back with `NO_XQUEUE`; code fix is compile verified and pending manual rerun. |
| `UXSCHED_CUDA_RUNTIME_STRATEGY=HB_RUNTIME` | IMPLEMENTED | Explicit Native fallback: runtime not implemented yet. |
| `UXSCHED_CUDA_RUNTIME_STRATEGY=AUTO` | IMPLEMENTED | Explicit Native fallback: coordinator unavailable. |
| Per-device HB coordinator | BLOCKED | Not implemented. |
| HB state machine | BLOCKED | Not implemented. |
| Kernel profiler / SplitPlan cache | BLOCKED | Not implemented. |
| kernel-tick launcher | BLOCKED | Not implemented. |
| small bubble hints | BLOCKED | Not implemented. |
| large bubble / consolidation | BLOCKED | Not implemented. |
| GPU visibility | RUNTIME VERIFIED | User manual WSL Gate 1 run used RTX 5060 and recorded `cuda_available=true`; do not reuse earlier Codex tool-session GPU blocker as current status. |
| open_resnet_like GPU validation | FAILED | Native and UXSched Native ran; HB_FIXED LP did not split because `KernelLaunch.xqueue` was null. |
| CUDA stream to XQueue association fix | COMPILE VERIFIED | Adds launch-time auto-association, default-stream synthetic context handle, and `UXSCHED_XQUEUE_TRACE=1`; pending manual GPU rerun. |
| CUTLASS workload | BLOCKED | Must wait until Gate 8. |
| Persistent agent rules | IMPLEMENTED | Added `AGENTS.md` with UXSched-Hummingbird integration rules. |
| Gate 1 smoke runner | IMPLEMENTED | `tools/run_hb_gate1_smoke.sh` records per-case artifacts and xserver logs. |

## Completed

- Created Git branch `feature/hummingbird-split-backend`.
- Added `UXSCHED_ENABLE_HB_SPLIT` CMake option, default `OFF`.
- Added runtime backend mode selection:
  - `UXSCHED_CUDA_PREEMPT_BACKEND=NATIVE`
  - `UXSCHED_CUDA_PREEMPT_BACKEND=HB_SPLIT`
  - `UXSCHED_CUDA_PREEMPT_BACKEND=AUTO`
- Added runtime strategy mode selection:
  - `UXSCHED_CUDA_RUNTIME_STRATEGY=NATIVE`
  - `UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED`
  - `UXSCHED_CUDA_RUNTIME_STRATEGY=HB_RUNTIME`
  - `UXSCHED_CUDA_RUNTIME_STRATEGY=AUTO`
- Added `CudaRuntimeStrategy`, `NativeRuntimeStrategy`, and
  `HummingbirdRuntimeStrategy`.
- Added persistent project rules in `AGENTS.md`.
- Kept UXSched CUDA shim as the only CUDA hook entry.
- Routed module load/get/unload wrappers through UXSched HB-aware code:
  - `cuModuleLoad`
  - `cuModuleLoadData`
  - `cuModuleLoadDataEx`
  - `cuModuleGetFunction`
  - `cuModuleUnload`
- Added PTX offset transformation for verified kernels:
  - append `__hb_off_x/y/z`;
  - rewrite recognized `%ctaid.x/y/z` moves;
  - reject recognized grid-level sync tokens.
- Added hidden transformed module cache while keeping the application-visible
  module/function original for safe native fallback.
- Added fixed-size grid decomposition with default split size `512`.
- Added LP-only split selection based on negative queue priority environment.
- Added HP passthrough for non-negative priority.
- Added native fallback for missing PTX, unverified kernels, transform failure,
  missing XQueue, unsupported Lv2/Lv3 combination, unsupported axes, `extra`
  launch format, null `kernelParams`, and grids smaller than split size.
- Added `SplitCommandGroup` child completion tracking.
- Added per-XQueue LP split launch config `threshold=1, batch_size=1`.
- Added structured `[UXSCHED-HB]` logs.
- Added optional `[UXSCHED-XQUEUE]` diagnostics with `UXSCHED_XQUEUE_TRACE=1`.
- Added launch-time CUDA stream to XQueue auto-association for streams that did
  not pass through `XStreamCreate*`.
- Added default stream support through a per-context synthetic HwQueue handle.
- Added PTX-present unverified-kernel metadata so that fallback can report
  `KERNEL_NOT_VERIFIED`.
- Added minimal Driver API XQueue probe under `tools/hb_xqueue_probe.cpp`.
- Built `halcuda` and `shimcuda` with HB enabled.
- Built `halcuda` and `shimcuda` with default HB disabled.
- Updated `tools/run_hb_gate1_smoke.sh` to preserve Gate 1 smoke artifacts,
  split UXSched backend stats from workload-internal split stats, and run
  default/explicit stream probes.
- Built `xserver` and `xcli` in both `build-hb` and `build-native`.

## Partially Completed

- Completion group tracks all child command completion, but first CUDA launch
  error recovery is limited by current Lv1 `CudaQueueLv1` behavior, which asserts
  on failed CUDA launches.
- Module unload waits for all XQueues before unloading the hidden transformed
  module, but broader multi-threaded unload stress tests are still needed.
- Multi-dimensional grid splitting is implemented, but runtime validation has
  not been run on real GPU workloads yet.
- `cuLaunchKernelEx` remains native in stage 1.
- Manual Gate 1 is PARTIAL/FAILED until the user reruns and observes real
  transformed child launches plus checksum/output-hash equality.

## Not Completed

- Automatic split-size selection.
- Online kernel profiling.
- Bubble detection.
- Split-kernel consolidation.
- Kernel-tick scheduling.
- Hummingbird memory management or NVLink offload.
- CUDA Graph splitting.
- HB split combined with UXSched Lv2/Lv3.
- cuBLAS/cuDNN closed kernel splitting.
- CUTLASS ResNet-like workload implementation and validation.
- GPU runtime benchmark repeat runs.
- Per-device runtime coordinator, profiler, kernel-tick, bubble detection,
  consolidation, and CUTLASS remain intentionally unimplemented.

## Modified Files

- `CMakeLists.txt`
- `platforms/cuda/CMakeLists.txt`
- `platforms/RTX4060/CMakeLists.txt`
- `platforms/cuda/shim/include/xsched/cuda/shim/shim.h`
- `platforms/cuda/shim/src/intercept.cpp`
- `platforms/cuda/shim/src/shim.cpp`
- `platforms/cuda/hal/include/xsched/cuda/hal/common/handle.h`
- `platforms/cuda/hal/include/xsched/cuda/hal/hb_split/backend.h`
- `platforms/cuda/hal/include/xsched/cuda/hal/level1/cuda_queue.h`
- `platforms/cuda/hal/src/hb_split/backend.cpp`
- `platforms/cuda/hal/src/arch/arch.cpp`
- `platforms/cuda/hal/src/level1/cuda_queue.cpp`
- `platforms/cuda/hal/src/runtime/runtime_strategy.cpp`
- `tools/run_hb_gate1_smoke.sh`

## Added Files

- `platforms/cuda/hal/include/xsched/cuda/hal/hb_split/backend.h`
- `platforms/cuda/hal/src/hb_split/backend.cpp`
- `platforms/cuda/hal/include/xsched/cuda/hal/runtime/runtime_strategy.h`
- `platforms/cuda/hal/src/runtime/runtime_strategy.cpp`
- `docs/hummingbird_backend_design.md`
- `docs/hummingbird_backend_implementation.md`
- `docs/hummingbird_backend_test_plan.md`
- `docs/hummingbird_backend_results.md`
- `docs/hummingbird_runtime_reaudit.md`
- `docs/hummingbird_runtime_architecture.md`
- `docs/hummingbird_runtime_state_machine.md`
- `docs/hummingbird_runtime_profiler.md`
- `docs/hummingbird_runtime_bubble_detection.md`
- `docs/hummingbird_runtime_test_plan.md`
- `docs/hummingbird_runtime_results.md`
- `docs/codex_handoff.md`
- `AGENTS.md`
- `hb_integration_status.md`
- `tools/run_hb_gate1_smoke.sh`
- `tools/hb_xqueue_probe.cpp`
- `tools/build_hb_xqueue_probe.sh`

## Session Handoff

2026-06-24 NO_XQUEUE fix:

- Read manual result directory `results/hb_gate1_manual_20260624_163059`.
- Current real Gate 1 conclusion is FAIL/PARTIAL:
  - GPU was accessible in the user's WSL manual run.
  - Native open_resnet_like and UXSched Native ran.
  - HB_FIXED LP transformed PTX but actual launches fell back with
    `backend_selected=NATIVE reason=NO_XQUEUE`.
  - No transformed child launch was observed.
- Root cause: `XLaunchKernel` only looked up pre-existing XQueue mappings and
  default stream was hard-coded to `xqueue=nullptr`; the workload's explicit
  stream did not pass through the shim stream-create wrapper.
- Fix is COMPILE VERIFIED:
  - launch-time auto-association for missing managed CUDA streams;
  - per-context synthetic HwQueue handle for default stream;
  - `UXSCHED_XQUEUE_TRACE=1` diagnostics;
  - `KERNEL_NOT_VERIFIED` fallback metadata;
  - minimal default/explicit Driver API probe.
- Passed:
  - `tools/build_hb_xqueue_probe.sh build-hb/hb_xqueue_probe`
  - `cmake --build build-hb --target halcuda shimcuda -j2`
  - `cmake --build build-native --target halcuda shimcuda -j2`
  - `bash -n tools/run_hb_gate1_smoke.sh tools/build_hb_xqueue_probe.sh`
- Not run in Codex tool environment: GPU runtime validation.
- Required next task: user manual rerun of the minimal HB_FIXED LP probe and
  correctness-mode checksum/output-hash comparison.

2026-06-24 handoff refresh:

- Rebuilt `docs/codex_handoff.md` using the required fixed structure.
- Rechecked current Git and source state before writing the handoff.
- Current source truth: `HB_RUNTIME` and `AUTO` are explicit Native fallback
  paths in `platforms/cuda/hal/src/runtime/runtime_strategy.cpp`.
- Current next gated task remains Gate 1 GPU validation of `HB_FIXED`.
- Build checks passed for `build-hb` and `build-native` targets
  `halcuda shimcuda`.
- Historical note: this refresh observed GPU access blocked inside that Codex
  tool session. It must not override the later user manual WSL GPU result.

2026-06-24 Gate 1 attempt:

- Rechecked the current Codex tool-session environment instead of reusing the
  previous blocker:
  - `/dev/dxg` is not visible.
  - `/usr/lib/wsl/lib/libcuda.so.1` exists.
  - `nvidia-smi` reports GPU access blocked by the operating system.
  - `torch.cuda.is_available()` is `False`; `torch.cuda.device_count()` is `0`.
- Rebuilt:
  - `cmake --build build-hb --target halcuda shimcuda -j2`
  - `cmake --build build-native --target halcuda shimcuda -j2`
  - `cmake --build build-hb --target xserver xcli -j2`
  - `cmake --build build-native --target xserver xcli -j2`
- Confirmed paths:
  - `build-hb/platforms/cuda/libhalcuda.so`
  - `build-hb/platforms/cuda/libshimcuda.so`
  - `build-native/platforms/cuda/libhalcuda.so`
  - `build-native/platforms/cuda/libshimcuda.so`
  - `build-hb/service/xserver`
  - `build-hb/service/xcli`
  - `build-native/service/xserver`
  - `build-native/service/xcli`
  - `/home/zm/project/hummingbird/build-lite/benchmarks/hb_open_resnet_like_eval`
  - `/home/zm/project/hummingbird/build-lite/benchmarks/hb_open_resnet_like_runtime_eval`
- Added and ran `tools/run_hb_gate1_smoke.sh`.
- Final artifact directory: `results/hb_gate1_20260624_162217`.
- Artifact results:
  - Native open_resnet_like: BLOCKED, `cuda_available=false`.
  - UXSched `NATIVE`: BLOCKED, `cuda_available=false`.
  - UXSched `HB_FIXED`: BLOCKED, `cuda_available=false`.
  - HP passthrough probe: BLOCKED, `cuda_available=false`.
  - fallback probe: BLOCKED, `cuda_available=false`.
  - event-boundary probe: BLOCKED, `cuda_available=false`.
  - xserver started with HPF, accepted UXSched clients, and stopped.
- No checksum, split trace, transformed CUfunction launch evidence, or child
  completion evidence was observed because no CUDA kernel was launched.
- Global Lv1 HPF smoke was not run because single-process GPU execution did not
  pass.

2026-06-24:

- Added `AGENTS.md` with permanent UXSched-Hummingbird integration rules.
- Created `docs/codex_handoff.md`.
- No source code behavior changed in this session.
- Hummingbird repository remained read-only.

## Build Results

Passed:

```bash
cmake -S . -B build-hb -DPLATFORM_CUDA=ON -DUXSCHED_ENABLE_HB_SPLIT=ON -DBUILD_TEST=OFF -DCMAKE_INSTALL_INCLUDEDIR=include
cmake --build build-hb --target halcuda shimcuda -j2
```

Passed:

```bash
cmake -S . -B build-native -DPLATFORM_CUDA=ON -DBUILD_TEST=OFF -DCMAKE_INSTALL_INCLUDEDIR=include
cmake --build build-native --target halcuda shimcuda -j2
```

Passed:

```bash
cmake --build build-hb --target xserver xcli -j2
cmake --build build-native --target xserver xcli -j2
```

## Test Results

Compile checks passed for the current NO_XQUEUE fix:

```bash
tools/build_hb_xqueue_probe.sh build-hb/hb_xqueue_probe
cmake --build build-hb --target halcuda shimcuda -j2
cmake --build build-native --target halcuda shimcuda -j2
bash -n tools/run_hb_gate1_smoke.sh tools/build_hb_xqueue_probe.sh
```

Manual GPU runtime result currently on record:

```text
results/hb_gate1_manual_20260624_163059
```

This manual run had GPU access and reached real CUDA execution, but HB_FIXED LP
fell back with `NO_XQUEUE` and did not submit transformed child launches. After
the current fix, Gate 1 must be manually rerun. Passing evidence must include:

```text
uxsched_hb_no_xqueue_count=0
uxsched_hb_child_launch_count > 1
transformed CUfunction child_launch_submitted logs
child_launch_completed / parent_launch_completed logs
Native, UXSched NATIVE, and HB_FIXED checksum/output_hash equality
```

## Fallback Behavior

`STRICT=0` returns to the original UXSched native launch path whenever splitting
is unsupported. The original module and original `CUfunction` remain available
because transformed code is loaded into a hidden module.

## Known Risks

1. The PTX transformer only rewrites recognized `mov.u32 ..., %ctaid.*`
   patterns. Kernels compiled into different PTX forms will fall back native.
2. Runtime cannot prove block independence or non-persistence; verified kernel
   names are required before splitting.
3. `extra` launch format is not split because current command ownership for
   `extra_` is raw-pointer based.

## Interface Reserved for Future Work

- split-size policy can be added before `DecomposeGrid`;
- kernel-tick can be modeled as LaunchWorker pacing after split commands exist;
- bubble detection/consolidation can be added above backend selection without
  adding a second scheduler;
- CUTLASS support requires separate PTX transformability and correctness
  validation.
