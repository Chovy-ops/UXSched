# Codex Development Handoff

## Source of truth

The source-of-truth priority is:

1. Current Git working tree and committed source code
2. `AGENTS.md`
3. `hb_integration_status.md`
4. Runtime and test documents
5. Previous chat text

If documents conflict with code, report the conflict and follow the code.

Current source-code check: `platforms/cuda/hal/src/runtime/runtime_strategy.cpp`
shows `HB_RUNTIME` and `AUTO` return explicit Native fallback, so any document
describing them as complete conflicts with code and must be treated as stale.

## Repository state

* Repository: `/home/zm/project/UXSched`
* Current branch: `feature/hummingbird-split-backend`
* HEAD commit at the start of the current NO_XQUEUE fix:
  `d8697de record Gate 1 GPU smoke blocker`
* Baseline commit: `4146c1e add CUDA Hummingbird split backend`
* Working tree status: clean except untracked build and result directories after
  committing this documentation/test-runner update
* Untracked files:
  * `build-hb/`
  * `build-native/`
  * `results/`

## Relevant commits

Chronological order:

* `4146c1e add CUDA Hummingbird split backend`
  * Added the initial compile-verified fixed split backend under UXSched's CUDA
    hook path.
* `038347d refactor CUDA backend into runtime strategies`
  * Added `CudaRuntimeStrategy`, `NativeRuntimeStrategy`, and
    `HummingbirdRuntimeStrategy`; moved `cuLaunchKernel` backend selection out
    of `shim.cpp`.
* `310bb42 tighten HB fixed runtime fallback semantics`
  * Prevented unimplemented `HB_RUNTIME`/`AUTO` from triggering PTX transform
    at module-load time.
* `cf48dae record HB runtime GPU gate status`
  * Recorded that GPU access is blocked and Gate 1 cannot run in the current
    environment.
* `f1a9c86 document UXSched Hummingbird agent rules`
  * Added `AGENTS.md`, created this handoff file, and updated status rules.
* `f605e8d refresh Codex handoff status`
  * Refreshed the handoff before the current Gate 1 attempt.
* `d8697de record Gate 1 GPU smoke blocker`
  * Added the Gate 1 smoke runner and recorded the earlier Codex tool-session
    GPU visibility blocker.

## Implemented and verified

| Item | Implemented | Compile verified | Runtime verified | Correctness verified | Performance verified |
| --- | --- | --- | --- | --- | --- |
| `UXSCHED_ENABLE_HB_SPLIT` CMake option | yes | yes | no | no | no |
| UXSched-only CUDA hook path | yes | yes | no | no | no |
| `CudaRuntimeStrategy` interface | yes | yes | no | no | no |
| `NativeRuntimeStrategy` | yes | yes | no | no | no |
| `HummingbirdRuntimeStrategy` shell | yes | yes | no | no | no |
| `NATIVE` strategy path | yes | yes | no | no | no |
| `HB_FIXED` strategy path | yes | yes | no | no | no |
| `HB_RUNTIME` mode | fallback only | yes | no | no | no |
| `AUTO` mode | fallback only | yes | no | no | no |
| PTX transformation | yes | yes | no | no | no |
| Hidden transformed module | yes | yes | no | no | no |
| Fixed grid decomposition | yes | yes | no | no | no |
| `SplitCommandGroup` child tracking | yes | yes | no | no | no |
| Per-XQueue threshold change to `1,1` | yes | yes | no | no | no |
| Gate 1 smoke runner | yes | yes | partial | no | no |
| CUDA stream to XQueue trace and auto-association | yes | yes | pending manual GPU rerun | no | no |
| GPU runtime benchmarks | no | no | no | no | no |

Compilation success is not runtime verification. No performance numbers are
claimed.

## Current known state

* NativeRuntimeStrategy:
  * COMPILE VERIFIED.
  * Source: `platforms/cuda/hal/src/runtime/runtime_strategy.cpp`,
    `NativeRuntimeStrategy::SubmitKernel`.
  * Builds a `CudaKernelLaunchCommand` and either direct-launches or submits to
    XQueue.
* HummingbirdRuntimeStrategy:
  * COMPILE VERIFIED.
  * Source: `platforms/cuda/hal/src/runtime/runtime_strategy.cpp`,
    `HummingbirdRuntimeStrategy::SubmitKernel`.
  * `HB_FIXED` delegates to `hb_split::TryLaunchKernelFixed`.
  * `HB_RUNTIME` and `AUTO` explicitly fallback Native.
* HB_FIXED:
  * COMPILE VERIFIED, Gate 1 remains FAIL/PARTIAL pending manual GPU rerun.
  * Source: `platforms/cuda/hal/src/hb_split/backend.cpp`,
    `TryLaunchKernelFixed`, `SubmitSplitCommands`.
  * The manual GPU run in `results/hb_gate1_manual_20260624_163059` reached
    PTX transform but fell back with `reason=NO_XQUEUE` before any transformed
    child launch.
* HB_RUNTIME:
  * IMPLEMENTED as Native fallback only.
  * Source: `HummingbirdRuntimeStrategy::SubmitKernel`, fallback reason
    `HB_RUNTIME_NOT_IMPLEMENTED_YET`.
* AUTO:
  * IMPLEMENTED as Native fallback only.
  * Source: `HummingbirdRuntimeStrategy::SubmitKernel`, fallback reason
    `AUTO_RUNTIME_COORDINATOR_UNAVAILABLE`.
* PTX transformation:
  * COMPILE VERIFIED, NOT TESTED on GPU.
  * Source: `TransformKernelPtx`, `TransformModulePtx`.
* hidden transformed module:
  * COMPILE VERIFIED, NOT TESTED on GPU.
  * Source: `TransformModulePtx`, `XModuleGetFunction`, `XModuleUnload`.
* grid decomposition:
  * COMPILE VERIFIED, NOT TESTED on GPU.
  * Source: `DecomposeGrid`, `DecomposeBox`.
* SplitCommandGroup:
  * COMPILE VERIFIED, NOT TESTED.
  * Source: `SplitCommandGroup` and state listener inside
    `SubmitSplitCommands`.
  * It tracks child completion and clears child ownership; it is not an
    application-visible parent completion primitive.
* per-XQueue threshold:
  * COMPILE VERIFIED, NOT TESTED on GPU.
  * Source: `SetLpSplitThresholdOnce`.
* HP passthrough:
  * COMPILE VERIFIED, NOT TESTED on GPU.
  * Source: `TryLaunchKernelFixed`, `IsLowPriority`, log reason
    `HIGH_PRIORITY_PASSTHROUGH`.
* fallback:
  * COMPILE VERIFIED, pending manual GPU rerun.
  * Sources: `TryLaunchKernelFixed`, `SubmitKernelWithRuntimeStrategy`.
  * PTX-present but unverified kernels now register `FunctionInfo` and fall back
    as `KERNEL_NOT_VERIFIED` instead of `<unknown>/PTX_UNAVAILABLE`.
* Gate 1 smoke runner:
  * IMPLEMENTED as `tools/run_hb_gate1_smoke.sh`.
  * Saves per-case `command.txt`, `env.txt`, stdout/stderr, JSONL, return code,
    checksum extraction, split trace extraction, transformed launch evidence,
    child completion evidence, parent completion evidence, and xserver logs.
  * Now writes UXSched backend stats separately from workload-internal split
    stats and includes minimal default/explicit Driver API XQueue probes.
* profiler:
  * BLOCKED, not implemented.
* kernel-tick:
  * BLOCKED, not implemented.
* small-bubble detection:
  * BLOCKED, not implemented.
* large-bubble consolidation:
  * BLOCKED, not implemented.
* CUTLASS workload:
  * BLOCKED, not implemented.

## Known gaps and risks

* `platforms/cuda/hal/src/hb_split/backend.cpp::TransformKernelPtx`
  * Rewrites only recognized `mov.u32 ..., %ctaid.x/y/z` PTX forms.
  * Does not prove full block independence.
* `platforms/cuda/hal/src/hb_split/backend.cpp::ContainsCrossBlockSync`
  * Detects only a few grid-level synchronization tokens:
    `grid.sync`, `griddepcontrol`, `barrier.cluster`.
* `platforms/cuda/hal/src/hb_split/backend.cpp::SubmitSplitCommands`
  * Submits all child commands immediately to XQueue.
  * No kernel-tick or bubble-aware pacing exists.
* `platforms/cuda/hal/src/hb_split/backend.cpp::SplitCommandGroup`
  * Tracks child completion via listeners but does not integrate as a parent
    command in XQueue.
* `platforms/cuda/hal/src/runtime/runtime_strategy.cpp::HummingbirdRuntimeStrategy::SubmitKernel`
  * `HB_RUNTIME` and `AUTO` are explicit Native fallbacks.
* `platforms/cuda/shim/src/shim.cpp::XLaunchKernelEx`
  * `cuLaunchKernelEx` remains native and is not split.
* `platforms/cuda/hal/src/hb_split/backend.cpp::TryLaunchKernelFixed`
  * `extra` launch format falls back Native.
* `platforms/cuda/hal/src/hb_split/backend.cpp::SetLpSplitThresholdOnce`
  * Threshold is applied per XQueue after first split attempt and has not been
    GPU validated under Global HPF.

## Current blocker

Blocker type: Gate 1 `HB_FIXED` did not reach UXSched split launch in the manual
GPU run.

Manual result directory:

```text
results/hb_gate1_manual_20260624_163059
```

Observed manual GPU result:

* Native open_resnet_like ran on RTX 5060.
* UXSched shim loaded and xserver accepted clients.
* HP priority `10` logged `HIGH_PRIORITY_PASSTHROUGH`.
* LP priority `-10` transformed at least the open_resnet_like PTX kernels, but
  actual launches fell back with `backend_selected=NATIVE reason=NO_XQUEUE`.
* `transformed_launch_evidence.log` showed no transformed child launch.
* `sync_event_boundary_probe` workload fields such as `lp_split_launched=1402`
  and `fixed_split_blocks=16` are workload-internal split counters, not UXSched
  backend split evidence.

Root cause found in code: `cuLaunchKernel` only looked up an already-registered
XQueue by raw `CUstream`; stream creation from the workload did not pass through
the shim's `XStreamCreate*` wrapper, and default stream was explicitly mapped to
`xqueue=nullptr`. The current fix adds launch-time auto-association for missing
managed streams and a per-context synthetic handle for default stream. This is
COMPILE VERIFIED only until the user reruns the manual GPU probe.

## Next task

The next gated task is a manual GPU rerun of the minimal `HB_FIXED` LP probe and
then correctness-mode Native/UXSched Native/HB_FIXED comparison.

Do not start the complete Hummingbird runtime, coordinator, profiler,
kernel-tick, bubble detection, consolidation, or CUTLASS workload until Gate 1
passes.

## Exact commands

Build commands:

```bash
cd /home/zm/project/UXSched
cmake -S . -B build-hb \
  -DPLATFORM_CUDA=ON \
  -DUXSCHED_ENABLE_HB_SPLIT=ON \
  -DBUILD_TEST=OFF \
  -DCMAKE_INSTALL_INCLUDEDIR=include
cmake --build build-hb --target halcuda shimcuda -j2
cmake -S . -B build-native \
  -DPLATFORM_CUDA=ON \
  -DBUILD_TEST=OFF \
  -DCMAKE_INSTALL_INCLUDEDIR=include
cmake --build build-native --target halcuda shimcuda -j2
```

Last run in this handoff session:

```text
build-hb: Built target halcuda; Built target shimcuda
build-native: Built target halcuda; Built target shimcuda
```

Additional service targets built for Global Lv1 smoke preparation:

```bash
cmake --build build-hb --target xserver xcli -j2
cmake --build build-native --target xserver xcli -j2
```

Confirmed paths:

```text
/home/zm/project/UXSched/build-hb/platforms/cuda/libhalcuda.so
/home/zm/project/UXSched/build-hb/platforms/cuda/libshimcuda.so
/home/zm/project/UXSched/build-native/platforms/cuda/libhalcuda.so
/home/zm/project/UXSched/build-native/platforms/cuda/libshimcuda.so
/home/zm/project/UXSched/build-hb/service/xserver
/home/zm/project/UXSched/build-hb/service/xcli
/home/zm/project/UXSched/build-native/service/xserver
/home/zm/project/UXSched/build-native/service/xcli
/home/zm/project/hummingbird/build-lite/benchmarks/hb_open_resnet_like_eval
/home/zm/project/hummingbird/build-lite/benchmarks/hb_open_resnet_like_runtime_eval
/home/zm/project/UXSched/build-hb/hb_xqueue_probe
```

Minimal manual retest after this fix:

```bash
cd /home/zm/project/UXSched
tools/build_hb_xqueue_probe.sh build-hb/hb_xqueue_probe

env -u LD_PRELOAD -u XSCHED_POLICY build-hb/service/xserver HPF 50000 \
  > /tmp/uxsched_hb_gate1_xserver.out 2> /tmp/uxsched_hb_gate1_xserver.err &
XSERVER_PID=$!

env -u XSCHED_POLICY -u HB_TASK_PRIORITY \
  LD_LIBRARY_PATH=/home/zm/project/UXSched/build-hb/platforms/cuda:/home/zm/project/UXSched/build-hb/preempt:/usr/lib/wsl/lib \
  LD_PRELOAD=/home/zm/project/UXSched/build-hb/platforms/cuda/libshimcuda.so \
  XSCHED_CUDA_LIB=/usr/lib/wsl/lib/libcuda.so.1 \
  CUXTRA_CUDA_LIB=/usr/lib/wsl/lib/libcuda.so.1 \
  XSCHED_SCHEDULER=GLB \
  XSCHED_AUTO_XQUEUE=ON \
  XSCHED_AUTO_XQUEUE_LEVEL=1 \
  XSCHED_AUTO_XQUEUE_PRIORITY=-10 \
  UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED \
  UXSCHED_XQUEUE_TRACE=1 \
  UXSCHED_HB_SPLIT_BLOCKS=512 \
  UXSCHED_HB_STRICT=0 \
  UXSCHED_HB_VERIFIED_KERNELS=hb_xqueue_probe_kernel \
  build-hb/hb_xqueue_probe --stream default --blocks 1024 --threads 1

env -u XSCHED_POLICY -u HB_TASK_PRIORITY \
  LD_LIBRARY_PATH=/home/zm/project/UXSched/build-hb/platforms/cuda:/home/zm/project/UXSched/build-hb/preempt:/usr/lib/wsl/lib \
  LD_PRELOAD=/home/zm/project/UXSched/build-hb/platforms/cuda/libshimcuda.so \
  XSCHED_CUDA_LIB=/usr/lib/wsl/lib/libcuda.so.1 \
  CUXTRA_CUDA_LIB=/usr/lib/wsl/lib/libcuda.so.1 \
  XSCHED_SCHEDULER=GLB \
  XSCHED_AUTO_XQUEUE=ON \
  XSCHED_AUTO_XQUEUE_LEVEL=1 \
  XSCHED_AUTO_XQUEUE_PRIORITY=-10 \
  UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED \
  UXSCHED_XQUEUE_TRACE=1 \
  UXSCHED_HB_SPLIT_BLOCKS=512 \
  UXSCHED_HB_STRICT=0 \
  UXSCHED_HB_VERIFIED_KERNELS=hb_xqueue_probe_kernel \
  build-hb/hb_xqueue_probe --stream explicit --blocks 1024 --threads 1

kill "${XSERVER_PID}"
wait "${XSERVER_PID}" 2>/dev/null || true
```

Reusable smoke wrapper:

```bash
cd /home/zm/project/UXSched
bash tools/run_hb_gate1_smoke.sh --output-dir results/hb_gate1_<timestamp>
```

Manual artifact directory that exposed the current blocker:

```text
results/hb_gate1_manual_20260624_163059
```

Manual artifact status:

```text
native_open_resnet_like_lp: RAN on GPU
uxsched_native_lp: RAN on GPU
uxsched_hb_fixed_lp: RAN but fell back Native with reason=NO_XQUEUE
uxsched_hb_fixed_hp_passthrough: RAN with HIGH_PRIORITY_PASSTHROUGH
sync_event_boundary_probe: workload-internal split counters only; no UXSched split trace
xserver: started with HPF, accepted clients, then stopped
```

Gate 1 remains FAIL/PARTIAL until a fresh manual run observes
`uxsched_hb_no_xqueue_count=0`, transformed child submissions, child completion,
and checksum/output hash equality.

## Expected outputs

Expected build output:

```text
Built target halcuda
Built target shimcuda
```

Expected runtime logs for `HB_FIXED` Gate 1:

* `[UXSCHED-HB] transform_succeeded function=<kernel>`
* `[UXSCHED-HB] transformed_module_loaded transformed_module=<...>`
* `[UXSCHED-HB] backend_selected=HB_SPLIT`
* `[UXSCHED-HB] split_blocks=512`
* `[UXSCHED-HB] split_count=<N>` where `N > 1`
* `[UXSCHED-HB] child_launch_submitted ... transformed_function=<...>`
* `[UXSCHED-HB] child_launch_completed ...`
* `[UXSCHED-HB] xqueue=<...> lp_in_flight_threshold=1 batch_size=1`
* `[UXSCHED-XQUEUE] ... auto_create_attempted=1 create_result=0 ...`
* HP run logs include `HIGH_PRIORITY_PASSTHROUGH`
* Unsupported kernel logs include `backend_selected=NATIVE reason=<reason>`

Expected PASS conditions:

* Native and `HB_FIXED` checksums match.
* LP produces more than one real split launch.
* The transformed `CUfunction` is actually submitted.
* HP kernels are not split.
* Native fallback path completes successfully.
* Event, stream, context/device synchronization semantics do not complete early.
* Global Lv1 HPF smoke test passes without falling back to a local scheduler.

Expected result locations should be created by the chosen smoke script, not by
this handoff file. Do not claim numeric performance until repeat runs exist.

## Do not do next

Do not begin any of the following until Gate 1 passes:

* per-device Hummingbird runtime coordinator;
* Hummingbird runtime state machine;
* kernel profiler or automatic `SplitPlan`;
* kernel-tick LP launcher;
* small-bubble detection or explicit bubble hint API;
* large-bubble detection;
* split-kernel consolidation;
* CUTLASS ResNet-like workload;
* performance claims or repeat=3 benchmark summaries.

## Session completion checklist

Before ending a session:

1. Run `git status`.
2. Run build checks.
3. Run available tests.
4. Update this file.
5. Update `hb_integration_status.md`.
6. Commit relevant source and documentation changes separately.
7. Print the next manual command for the user.
