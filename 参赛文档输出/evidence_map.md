# 证据映射

| claim | document_section | evidence_type | source_file | verified_value | notes |
|---|---|---|---|---|---|
| 用户态CUDA API拦截 | 5.1 | 源码 | platforms/cuda/shim/src/intercept.cpp | DEFINE_EXPORT_C_REDIRECT_CALL覆盖大量Driver API | CUDA Driver API shim |
| Runtime launch bridge | 5.3 | 源码 | platforms/cuda/shim/src/runtime_intercept.cpp | runtime_launch_intercepted/function_resolved/metadata bridge | CUTLASS Runtime launch进入HB backend |
| Global HPF | 4.3 | 源码/日志 | tools/run_cutlass_realtime_compare.sh | xserver HPF 50000, global_scheduler_log_pass=1 | 五轮均通过 |
| HP/LP优先级 | 7.3 | 配置 | tools/run_cutlass_realtime_compare.sh | HP priority=10, LP priority=-10 | 两进程并发 |
| 原始UXSched四场景数据 | 8.1 | CSV | original comparison.csv | P99 46.22/137.40/47.68/48.61 ms | repeat=5 |
| CUTLASS HP Mean/P95/P99 | 8.2 | CSV | CUTLASS comparison.csv | Unsplit 3233.503/4390.938/4603.048 us; HB 1863.444/2194.780/2310.521 us | repeat=5 |
| P99降低49.76% | 8.3 | CSV | comparison.csv ratio_aggregate | 49.76% | paired repeat ratio |
| LP throughput retention | 8.4 | CSV | comparison.csv | retention 57.29%, loss 42.71% | 吞吐代价明确报告 |
| split_blocks=52 | 6.2 | 资源推导/配置 | metadata.env, docs | 26 SM * 2 resident blocks/SM = 52 | 固定配置 |
| split_blocks=52公式输入 | 6.2 | 资源推导/日志/源码 | split52_formula_verification.md, final_report.md, verified_kernel_sm120_fp32_simt.txt, Runtime launch logs | SM=26, threads/block=256, registers/thread=128, dynamic shared memory=16640 bytes | Codex工具环境NVML受限，正式sweep runner会在用户GPU终端重新保存nvidia-smi |
| 线程/共享内存/寄存器限制 | 6.2 | 资源推导 | split52_formula_verification.md | 6 / 5 / 2 blocks per SM，寄存器主导 | 52是固定公式推导值，不是自动profiling |
| 32/52/64/128正式sweep | 6.3 | 待GPU重测 | tools/run_cutlass_split_size_sweep.sh, aggregate_cutlass_split_size_sweep.py | 待用户手动运行统一repeat=5 sweep后填入 | 不混用历史repeat=1/3结果 |
| parent/child数量 | 5.5/8.5 | 日志统计 | uxsched_backend_stats.env | r0 parent=2446 child=14676; r1 parent=2426 child=14556; r2 parent=2426 child=14556; r3 parent=2427 child=14562; r4 parent=2397 child=14382 | 每parent约6 child |
| metadata bridge | 5.3 | 日志统计 | uxsched_backend_stats.env | runtime_hb_metadata_bridge_pass=1 for repeat 0..4 | 五轮通过 |
| verified kernel | 5.4 | 配置 | benchmarks/cutlass/verified_kernel_sm120_fp32_simt.txt | 精确mangled kernel allowlist | 不使用通配符 |
| LP transform | 5.5 | 统计 | uxsched_backend_stats.env | warmup transform_count=1, measurement delta=0 | 冷启动隔离 |
| HP passthrough | 5.6 | 统计 | uxsched_backend_stats.env | hp_hb_transform_count=0 | HP不切分 |
| fallback=0/no_xqueue=0 | 5.7/8.5 | 统计 | uxsched_backend_stats.env | hb_fallback_count_delta=0, hb_no_xqueue_count_delta=0 | 五轮通过 |
| 正确性 | 7.5 | CSV/JSONL | summary.csv/output.jsonl | correctness_pass=1 | 所有正式case通过 |
| GPU/CUDA/CUTLASS环境 | 7.1 | metadata | metadata.env | CUDA 12.8, SM120, CUTLASS revision ad7b2f5 | RTX 5060 Laptop GPU |
| 关键Git提交 | 附录 | git | git log | UXSched HEAD 0af7f6a; original 5222f97 | 源码证据 |
| 无内核和驱动修改 | 4.5/9.4 | 设计/源码 | shim+xserver+runner | LD_PRELOAD用户态hook, libcuda只作为真实driver入口 | 无OS kernel/driver patch |
