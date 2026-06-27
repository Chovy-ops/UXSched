# Conservative Bubble-Aware MVP

This document describes the first executable bubble-aware scheduling path in
HB-UXSched. It is intentionally conservative and disabled by default.

## Goal

The MVP allows one low-priority Hummingbird child kernel to be submitted only
when all of the following conditions hold:

- `UXSCHED_BUBBLE_AWARE=ON` is set.
- An explicit bubble-open hint has been received.
- No high-priority work is marked pending.
- No low-priority child kernel is in flight.
- The low-priority parent kernel has already passed the existing `HB_FIXED`
  splitting checks.

If high-priority work arrives, a bubble-close hint is received, or the state is
inconsistent, the controller stops submitting new low-priority child kernels.
It does not interrupt a CUDA kernel that is already executing; that child is
allowed to finish naturally.

## Explicit Hint Mode

The current implementation uses explicit hints:

- `UXSchedBubbleOpenHint()`
- `UXSchedBubbleCloseHint()`
- `UXSchedBubbleHpEnqueueHint()`
- `UXSchedBubbleHpQueueEmptyHint()`

These hooks drive a small state machine and are suitable for functional smoke
tests and for future benchmark integration. They are not a general automatic
bubble detector. In particular, `HP queue empty` is not treated as a bubble-open
event; a fresh explicit bubble-open hint is required.

## Environment Variables

- `UXSCHED_BUBBLE_AWARE=ON|OFF`

  Defaults to `OFF`. When disabled, the existing HB_FIXED submission behavior is
  preserved.

- `UXSCHED_BUBBLE_MAX_IN_FLIGHT=1`

  The MVP supports only one device-side low-priority child in flight. Any other
  value is clamped to 1 and logged as a warning.

- `UXSCHED_BUBBLE_FAIL_SAFE=ON|OFF`

  Defaults to `ON`. Inconsistent state closes the bubble window.

- `UXSCHED_BUBBLE_LOG=ON|OFF`

  Defaults to `ON` when bubble-aware mode is enabled.

## State Machine

The controller has four states:

- `DISABLED`: feature is off and the original path is preserved.
- `CLOSED`: no explicit bubble is open; new LP child launches are rejected.
- `OPEN`: explicit bubble is open. One LP child may be submitted if HP is not
  pending and no LP child is already in flight.
- `HP_ACTIVE`: HP work is pending. New LP child launches are rejected.

Transitions:

- `bubble_open`: `CLOSED -> OPEN`
- `bubble_close`: `OPEN -> CLOSED`
- `hp_enqueue`: `OPEN/CLOSED -> HP_ACTIVE`
- `hp_queue_empty`: `HP_ACTIVE -> CLOSED`

The `hp_queue_empty` transition deliberately returns to `CLOSED`, not `OPEN`.
This avoids treating absence of HP work as a complete bubble signal.

## HB_FIXED Gating Point

The gate is in `platforms/cuda/hal/src/hb_split/backend.cpp`, inside
`SubmitSplitCommands`, after the parent kernel has passed HB_FIXED capability
checks and has been decomposed into transformed child launches.

When bubble-aware mode is disabled, all children are submitted as before.

When bubble-aware mode is enabled:

1. The split group is registered as pending.
2. The controller attempts to acquire the single LP in-flight slot.
3. If the bubble is not open, HP is pending, or another LP child is in flight,
   the split group is not partially executed and the launch safely falls back to
   Native.
4. If the first child is submitted, later children are submitted one at a time
   from child-completion callbacks, and only while the controller still allows
   them.
5. If HP arrives or the bubble closes, remaining children stay pending until a
   later explicit bubble-open hint allows progress.

This design keeps `max_lp_in_flight <= 1` and prevents new LP child launches
after HP is marked pending. It does not withdraw an already executing child.

## Counters

The process logs a `bubble_stats` line containing:

- `bubble_open_count`
- `bubble_close_count`
- `bubble_fill_attempt_count`
- `bubble_fill_success_count`
- `bubble_fill_rejected_count`
- `bubble_reject_hp_pending_count`
- `bubble_reject_no_hint_count`
- `bubble_reject_lp_in_flight_count`
- `lp_child_launched_in_bubble_count`
- `hp_arrival_during_lp_child_count`
- `stop_new_lp_on_hp_count`
- `max_lp_in_flight`
- `bubble_fail_safe_count`

Event logs use the prefix `[UXSCHED-BUBBLE]` and include timestamp, event name,
priority, state, HP pending count, LP in-flight count, parent launch ID, and
child launch ID where available.

## Fail-Safe Behavior

The controller closes the bubble window and increments `bubble_fail_safe_count`
when it observes inconsistent state, such as an LP child completion without a
matching in-flight child. A fail-safe close never enables more LP work.

## Tests

CPU-side tests are provided by:

```bash
tools/run_bubble_aware_mvp_selftest.sh
```

The test covers:

- default disabled behavior;
- rejecting LP in `CLOSED`;
- allowing one LP child in `OPEN`;
- rejecting a second LP child while one is in flight;
- rejecting LP after HP enqueue;
- requiring a fresh bubble-open hint after HP queue empty;
- rejecting LP after bubble close;
- fail-safe close on inconsistent completion.

Log-order checks are provided by:

```bash
python3 tools/check_bubble_aware_mvp_log.py <log>
```

The checker verifies that no `lp_child_launch_in_bubble` event appears after
`hp_enqueue` and before `hp_queue_empty`, and that LP in-flight counts do not
exceed 1.

## Real CUDA/HB_FIXED Smoke

The real CUDA smoke is prepared but is not run automatically by Codex:

```bash
tools/run_bubble_aware_gpu_smoke.sh --output-dir results/bubble_aware_gpu_smoke_$(date +%Y%m%d_%H%M%S)
```

The smoke reuses the existing CUTLASS FP32 SIMT GEMM launch probe and runs it in
the same process as the UXSched CUDA shim. The probe resolves the explicit hint
symbols with `dlsym(RTLD_DEFAULT, ...)`, so the hint API and the HB_FIXED backend
share the same process-local controller instance.

Cases:

- `case_off`: `UXSCHED_BUBBLE_AWARE=OFF`; verifies that the existing HB_FIXED
  split path still completes without requiring hints.
- `case_explicit_open`: opens a bubble, launches a real HB_FIXED parent, waits
  for real child launch/completion, and then closes the bubble.
- `case_hp_active`: opens a bubble, starts an HB_FIXED parent, marks HP pending,
  launches and synchronizes a tiny real CUDA HP kernel on a separate stream with
  `UXSCHED_HB_PRIORITY=10`, verifies that no further LP child launches occur
  during the HP_ACTIVE window, then closes HP and sends a fresh bubble-open hint
  to allow progress. The HP kernel is a no-op functional marker and is not a
  performance workload.
- `case_no_hint`: enables bubble-aware mode without opening a bubble; the first
  LP split attempt is rejected as `BUBBLE_DEFERRED`/`cudaErrorNotReady`. The
  test must show that no Hummingbird child is submitted and no Native LP kernel
  is launched.
- `case_fail_safe`: sends an abnormal repeated close sequence to exercise the
  fail-safe path, then verifies that no LP child launch and no Native LP launch
  occurs.

The runner writes per-case `stdout.log`, `stderr.log`, `bubble_events.jsonl`,
`bubble_stats.env`, `backend_stats.env`, and `status.env`, plus a top-level
`summary.csv`, `smoke_report.md`, and `status.env`.

The gate checker is:

```bash
python3 tools/check_bubble_aware_gpu_smoke.py --result-dir <RESULT_DIR>
```

It prints `BUBBLE_AWARE_GPU_SMOKE=PASS` only if all required cases satisfy the
functional gates. Passing this smoke would be a real GPU functional validation
of the explicit-hint MVP, not a performance result.

Important semantics:

- `HIGH_PRIORITY_PASSTHROUGH` is reported as `kPassthrough`, not as fallback.
  Runtime logs use `runtime_launch_passthrough task_role=HP is_fallback=0`.
- Bubble-gate rejection is reported as `kDeferredByBubbleGate`, not as fallback.
  Runtime logs use `runtime_backend_deferred ... is_fallback=0` and return
  `cudaErrorNotReady` to the smoke probe. The original LP kernel is not launched
  through Native.
- Only genuine LP fallback logs use `task_role=LP backend=NATIVE is_fallback=1`.
- `case_hp_active` waits for `UXSchedBubbleWaitForLpChildLaunch(1, timeout)` so
  HP enqueue occurs only after the first real LP child has been submitted.
- `case_no_hint` and `case_fail_safe` are expected-deferred negative tests; they
  do not run LP correctness and must not be presented as failed computation
  cases.
- Their machine-readable summary uses `status=EXPECTED_DEFERRED`,
  `expected_deferred_pass=1`, and `correctness_status=NOT_APPLICABLE` when the
  safety gates pass.
- HP passthrough is counted from the unique Runtime event
  `runtime_launch_passthrough`; the matching backend
  `HIGH_PRIORITY_PASSTHROUGH` line is supporting evidence and is not counted as
  a second launch.
- LP child events use the original parent split group's task metadata. Completion
  callbacks therefore log `task_priority=-10 task_role=LP` even if a different
  thread temporarily changes the process environment for the HP marker.

Current status:

- code path connected;
- CPU/mock self-test passes;
- `halcuda` and `shimcuda` build successfully;
- CUTLASS probe builds successfully;
- real CUDA end-to-end smoke passed in
  `results/bubble_aware_gpu_smoke_20260627_195834` with
  `BUBBLE_AWARE_GPU_SMOKE=PASS`, `case_count=5`, and `error_count=0`.

The passed smoke validates functionality only. It is not a P99, throughput,
GPU utilization, automatic detector, kernel-tick, or dynamic consolidation
result.

## Relation to Hummingbird Section 4.3

This MVP implements only the conservative launch-control subset needed to form
a verifiable bubble-use path. It is related to Hummingbird's runtime scheduler
in that low-priority work is admitted only in safe intervals and high-priority
arrival stops future low-priority submissions.

It does not implement the full Hummingbird mechanism:

- no automatic small-bubble detector;
- no host-side CUDA/NCCL pattern inference;
- no kernel-tick pacing based on measured child duration;
- no multi-child pre-submission;
- no dynamic large-bubble consolidation;
- no performance claim.

The next integration steps are to connect CUDA Runtime synchronization and
memcpy hints to the explicit hint interface, add kernel-tick pacing, and later
evaluate dynamic consolidation against the existing CUTLASS HB_FIXED backend.
