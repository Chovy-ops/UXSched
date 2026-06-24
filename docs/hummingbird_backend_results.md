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

2026-06-24 Gate 1 smoke was attempted with:

```bash
bash tools/run_hb_gate1_smoke.sh --output-dir results/hb_gate1_20260624_162217
```

The current Codex tool session did not have GPU access. Fresh checks showed
`/dev/dxg` was not visible, `nvidia-smi` reported GPU access blocked by the
operating system, and `torch.cuda.is_available()` returned `False`.

Artifact status:

| Case | Result |
| --- | --- |
| Native open_resnet_like LP | BLOCKED: `cuda_available=false` |
| UXSched `NATIVE` LP | BLOCKED: `cuda_available=false` |
| UXSched `HB_FIXED` LP | BLOCKED: `cuda_available=false` |
| UXSched `HB_FIXED` HP passthrough probe | BLOCKED: `cuda_available=false` |
| UXSched `HB_FIXED` unverified-kernel fallback probe | BLOCKED: `cuda_available=false` |
| Event-boundary sync probe | BLOCKED: `cuda_available=false` |
| xserver HPF | Started, accepted clients, stopped |

No benchmark numbers are claimed in this document.

Observed evidence:

- checksum: not observed;
- split trace: not observed;
- transformed CUfunction launch evidence: not observed;
- child completion evidence: not observed;
- parent completion: no-CUDA marker only;
- Global Lv1 HPF smoke: not run because single-process GPU execution did not
  pass.

Pending runtime checks:

- open_resnet_like HP passthrough;
- open_resnet_like LP split count and checksum;
- fallback for unsupported/non-PTX kernels;
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
