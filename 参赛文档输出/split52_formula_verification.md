# split_blocks=52 公式推导与参数核验

本文档用于补充 HB-UXSched 参赛文档第 6 章“固定切分粒度设计”。它只记录硬件资源公式和参数来源，不声称 `52` 是自动 profiling 结果或跨 GPU、跨 kernel 的全局最优值。

## 1. 参数与来源

| 参数 | 数值 | 来源 | 说明 |
|---|---:|---|---|
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU | `results/cutlass_realtime_compare_split52_repeat5_20260625_141255/nvidia_smi.txt` | 正式 CUTLASS repeat=5 实验环境 |
| SM count | 26 | 正式实验记录与 `final_report.md` 的 split=52 rationale | Codex 工具环境当前 NVML 被系统阻止，正式 sweep runner 会在用户 GPU 终端重新保存 `nvidia-smi` |
| max threads per SM | 1536 | RTX 5060 Laptop GPU / SM120 资源参数记录 | 用于线程驻留上限计算 |
| registers per SM | 65536 | RTX 5060 Laptop GPU / SM120 资源参数记录 | 用于寄存器驻留上限计算 |
| shared memory per SM | 102400 bytes | RTX 5060 Laptop GPU / SM120 资源参数记录 | 用于共享内存驻留上限计算 |
| threads per block | 256 | `benchmarks/cutlass/verified_kernel_sm120_fp32_simt.txt` 与 Runtime launch log `block=(256,1,1)` | CUTLASS FP32 SIMT GEMM kernel |
| registers per thread | 128 | `results/.../final_report.md` 中的 kernel 资源记录 | 当前 CUTLASS kernel 的寄存器占用 |
| static shared memory per block | 1024 bytes | 当前 CUTLASS kernel 资源记录 | 与 dynamic shared memory 相加计算 |
| dynamic shared memory per block | 16640 bytes | Runtime launch log `shared_mem=16640` | `runtime_intercept.cpp` 记录的真实 launch 参数 |

## 2. 资源约束公式

线程限制：

```text
thread_limit = floor(max_threads_per_SM / threads_per_block)
             = floor(1536 / 256)
             = 6 blocks/SM
```

共享内存限制：

```text
shared_memory_limit =
floor(shared_memory_per_SM / (static_smem_per_block + dynamic_smem_per_block))
= floor(102400 / (1024 + 16640))
= 5 blocks/SM
```

寄存器限制：

```text
register_limit =
floor(registers_per_SM / (registers_per_thread × threads_per_block))
= floor(65536 / (128 × 256))
= floor(65536 / 32768)
= 2 blocks/SM
```

因此当前 kernel 每个 SM 的理论驻留 block 数为：

```text
active_blocks_per_SM = min(6, 5, 2) = 2
```

固定切分粒度为：

```text
split_blocks = SM_count × active_blocks_per_SM
             = 26 × 2
             = 52 blocks
```

## 3. 结论与适用范围

寄存器约束是当前 CUTLASS FP32 SIMT GEMM kernel 的主导限制。`split_blocks=52` 表示按当前 GPU 的 26 个 SM 和每 SM 约 2 个可驻留 CUTLASS block 估算的一轮可驻留 block 数。

该值只适用于：

- 当前 RTX 5060 Laptop GPU；
- 当前 SM120 FP32 SIMT CUTLASS GEMM kernel；
- 当前 M=N=K=2048、threadblock shape 与资源占用；
- 当前 HB_FIXED 固定粒度切分实验。

它不是：

- Hummingbird 自动搜索得到的最优值；
- 运行时自动 profiling 结果；
- 适用于所有 GPU、所有 kernel 或所有输入规模的全局最优值。

正式参赛文档中的性能结论必须继续由统一配置下的 split-size sweep 支撑，即 `Unsplit、32、52、64、128` 在相同 M/N/K、HP 请求数、HP 周期、LP 时长、repeat 和 Global HPF 边界下的实测对比。
