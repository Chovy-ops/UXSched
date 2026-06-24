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

## 2. Runtime Results

GPU runtime tests were not run in this development pass. No benchmark numbers
are claimed in this document.

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

