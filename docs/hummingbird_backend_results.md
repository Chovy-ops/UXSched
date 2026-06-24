# Hummingbird Split Backend Results

## 1. Build Results

Baseline commit:

```text
73039c69e67a0e66bd28741e8784e7dda65749ed
```

Branch:

```text
feature/hummingbird-split-backend
```

Submodules were initially uninitialized. After running:

```bash
git submodule update --init --recursive
```

the required third-party sources were available.

### HB-enabled CUDA build

Command:

```bash
cmake -S . -B build-hb \
  -DPLATFORM_CUDA=ON \
  -DUXSCHED_ENABLE_HB_SPLIT=ON \
  -DBUILD_TEST=OFF \
  -DCMAKE_INSTALL_INCLUDEDIR=include
cmake --build build-hb --target halcuda shimcuda -j2
```

Result:

```text
Built target halcuda
Built target shimcuda
```

### Default native CUDA build

Command:

```bash
cmake -S . -B build-native \
  -DPLATFORM_CUDA=ON \
  -DBUILD_TEST=OFF \
  -DCMAKE_INSTALL_INCLUDEDIR=include
cmake --build build-native --target halcuda shimcuda -j2
```

Result:

```text
Built target halcuda
Built target shimcuda
```

### Service targets for Global Lv1 smoke

Command:

```bash
cmake --build build-hb --target xserver xcli -j2
cmake --build build-native --target xserver xcli -j2
```

Result:

```text
Built target xserver
Built target xcli
```

Confirmed paths:

```text
build-hb/platforms/cuda/libhalcuda.so
build-hb/platforms/cuda/libshimcuda.so
build-native/platforms/cuda/libhalcuda.so
build-native/platforms/cuda/libshimcuda.so
build-hb/service/xserver
build-hb/service/xcli
build-native/service/xserver
build-native/service/xcli
/home/zm/project/hummingbird/build-lite/benchmarks/hb_open_resnet_like_eval
/home/zm/project/hummingbird/build-lite/benchmarks/hb_open_resnet_like_runtime_eval
```

## 2. Runtime Results

2026-06-24 manual Gate 1 smoke result directory:

```text
results/hb_gate1_manual_20260624_163059
```

Artifact status:

| Case | Result |
| --- | --- |
| Native open_resnet_like LP | RAN on RTX 5060 |
| UXSched `NATIVE` LP | RAN with UXSched shim loaded |
| UXSched `HB_FIXED` LP | FAILED/PARTIAL: PTX transformed, launches fell back `NO_XQUEUE` |
| UXSched `HB_FIXED` HP passthrough probe | RAN: `HIGH_PRIORITY_PASSTHROUGH` |
| UXSched `HB_FIXED` unverified-kernel fallback probe | RAN, but old code reported `<unknown>/PTX_UNAVAILABLE`; fixed code must rerun |
| Event-boundary sync probe | RAN workload-internal split counters only; no UXSched split trace |
| xserver HPF | Started, accepted clients, stopped |

No benchmark numbers are claimed in this document.

Observed evidence:

- `transform_succeeded` appeared for open_resnet_like kernels;
- `backend_selected=NATIVE reason=NO_XQUEUE` appeared on LP launches;
- transformed CUfunction child launch evidence: not observed;
- child completion evidence: not observed;
- workload fields `lp_split_launched` and `fixed_split_blocks` are workload
  internal counters and are not UXSched backend split evidence;
- Global Lv1 HPF smoke: not run because single-process HB_FIXED split execution
  did not pass.

2026-06-24 NO_XQUEUE fix:

```text
COMPILE VERIFIED only; manual GPU rerun still required.
```

Implemented after the manual result:

- launch-time auto-association from CUDA stream to stable XQueue when
  `XSCHED_AUTO_XQUEUE=ON`;
- default stream support through a per-context synthetic HwQueue handle;
- `UXSCHED_XQUEUE_TRACE=1` logs for API, pid/tid, CUDA context, stream handle,
  default-stream flag, auto-create attempt/result, HwQueue/XQueue pointers,
  lookup result, `KernelLaunch.xqueue`, runtime strategy, and fallback path;
- `KERNEL_NOT_VERIFIED` fallback metadata for PTX entries that are present but
  excluded by the verified kernel list;
- explicit `transformed_module_loaded`, `parent_launch_submitted`,
  `child_launch_submitted`, `child_launch_completed`, and
  `parent_launch_completed` logs;
- minimal Driver API probe for default and explicit streams:
  `tools/hb_xqueue_probe.cpp`.

Build checks after this fix:

```bash
tools/build_hb_xqueue_probe.sh build-hb/hb_xqueue_probe
cmake --build build-hb --target halcuda shimcuda -j2
cmake --build build-native --target halcuda shimcuda -j2
bash -n tools/run_hb_gate1_smoke.sh tools/build_hb_xqueue_probe.sh
```

Pending runtime checks:

- minimal HB_FIXED LP default-stream probe;
- minimal HB_FIXED LP explicit-stream probe;
- open_resnet_like HP passthrough;
- open_resnet_like LP split count and checksum;
- separate `PTX_UNAVAILABLE` and `KERNEL_NOT_VERIFIED` fallback cases;
- event and stream synchronization after split groups;
- Global Scheduler / HPF end-to-end latency and throughput measurements.

## 3. Known Missing Results

- HP P50/P95/P99 latency for UXSched-HB AUTO;
- LP normalized throughput for UXSched-HB AUTO;
- estimated preemption delay with split size 512;
- transformation overhead;
- fallback count across workload runs;
- CUTLASS ResNet-like native run;
- CUTLASS transformability check.

## 4. Observed Build Notes

- The top-level CMake currently expects `CMAKE_INSTALL_INCLUDEDIR`; the build
  commands above pass `-DCMAKE_INSTALL_INCLUDEDIR=include`.
- `UXSCHED_ENABLE_HB_SPLIT` defaults to `OFF`.
- The backend compiles in both enabled and disabled builds.
- No Hummingbird source files were modified.
