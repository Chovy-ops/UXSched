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
* HEAD commit: `f1a9c8628d69e8270bbddae9a9221f7f386aa98d` at the time this handoff source audit was run
* Baseline commit: `4146c1e add CUDA Hummingbird split backend`
* Working tree status: clean except untracked build directories
* Untracked files:
  * `build-hb/`
  * `build-native/`

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
  * COMPILE VERIFIED, NOT TESTED on GPU.
  * Source: `platforms/cuda/hal/src/hb_split/backend.cpp`,
    `TryLaunchKernelFixed`, `SubmitSplitCommands`.
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
  * COMPILE VERIFIED, NOT TESTED on GPU.
  * Sources: `TryLaunchKernelFixed`, `SubmitKernelWithRuntimeStrategy`.
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

Blocker type: GPU device access.

Exact observed error:

```text
nvidia-smi
Failed to initialize NVML: GPU access blocked by the operating system
Failed to properly shut down NVML: GPU access blocked by the operating system
```

Because GPU access is blocked, Gate 1 cannot be executed. There is no evidence
yet for RUNTIME VERIFIED, CORRECTNESS VERIFIED, GLOBAL SCHEDULING VERIFIED, or
PERFORMANCE VERIFIED status.

## Next task

The next gated task is Gate 1 GPU validation of `HB_FIXED`.

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

GPU access check:

```bash
nvidia-smi
```

Last run in this handoff session:

```text
Failed to initialize NVML: GPU access blocked by the operating system
Failed to properly shut down NVML: GPU access blocked by the operating system
```

Manual Gate 1 smoke outline, once GPU access works:

```bash
cd /home/zm/project/UXSched
export LD_PRELOAD=/home/zm/project/UXSched/build-hb/platforms/cuda/libshimcuda.so
export XSCHED_SCHEDULER=GLB
export XSCHED_AUTO_XQUEUE=ON
export XSCHED_AUTO_XQUEUE_LEVEL=1
export XSCHED_AUTO_XQUEUE_PRIORITY=-10
export UXSCHED_CUDA_RUNTIME_STRATEGY=HB_FIXED
export UXSCHED_HB_SPLIT_BLOCKS=512
export UXSCHED_HB_STRICT=0
export UXSCHED_HB_VERIFIED_KERNELS=hb_open_resnet_conv2d_kernel,hb_open_resnet_relu_kernel,hb_open_resnet_residual_add_kernel,hb_open_resnet_checksum_kernel
```

Then run the existing PTX-visible open-resnet-like driver workload from
Hummingbird without modifying the Hummingbird repository. Use the user's known
script/workload entrypoint for the local environment.

## Expected outputs

Expected build output:

```text
Built target halcuda
Built target shimcuda
```

Expected runtime logs for `HB_FIXED` Gate 1:

* `[UXSCHED-HB] transform_succeeded function=<kernel>`
* `[UXSCHED-HB] backend_selected=HB_SPLIT`
* `[UXSCHED-HB] split_blocks=512`
* `[UXSCHED-HB] split_count=<N>` where `N > 1`
* `[UXSCHED-HB] xqueue=<...> lp_in_flight_threshold=1 batch_size=1`
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
