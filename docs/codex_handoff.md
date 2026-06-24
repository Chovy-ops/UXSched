# Codex Handoff

## Current Context

- Date: 2026-06-24
- UXSched path: `/home/zm/project/UXSched`
- Hummingbird path: `/home/zm/project/hummingbird`
- Python environment: `/home/zm/project/hummingbird/.venv`
- Current branch: `feature/hummingbird-split-backend`
- Hummingbird repository rule: read-only unless the user explicitly changes it.

## Recent Commits

```text
cf48dae record HB runtime GPU gate status
310bb42 tighten HB fixed runtime fallback semantics
038347d refactor CUDA backend into runtime strategies
4146c1e add CUDA Hummingbird split backend
```

## Current Implementation Status

- `NATIVE`: COMPILE VERIFIED.
- `HB_FIXED`: COMPILE VERIFIED, NOT TESTED on GPU.
- `HB_RUNTIME`: IMPLEMENTED as explicit Native fallback only.
- `AUTO`: IMPLEMENTED as explicit Native fallback only.
- GPU runtime validation: BLOCKED because `nvidia-smi` reported GPU access
  blocked by the operating system.

## Current Gate

Gate 1 is not passed. Do not implement the complete Hummingbird runtime,
coordinator, profiler, kernel-tick, small bubble, large bubble, consolidation,
or CUTLASS workload until HB_FIXED has real GPU correctness validation.

Gate 1 requires:

- HB_FIXED executes on a real GPU.
- LP produces more than one real split launch.
- The transformed CUfunction is actually submitted.
- Native and HB_FIXED checksums match.
- HP passthrough is verified.
- Native fallback is verified.
- Event, stream, context/device synchronization semantics are correct.
- Global Lv1 HPF smoke test passes without local fallback.

## Important Rules

Permanent rules are maintained in `AGENTS.md`. In short:

- UXSched is the only global scheduler.
- UXSched CUDA shim is the only CUDA hook.
- Do not use dual CUDA `LD_PRELOAD` hook libraries.
- Hummingbird is a CUDA runtime strategy inside UXSched.
- HP kernels always passthrough and are never split.
- Unsupported LP kernels must safely fallback Native.
- Compilation success is not runtime verification.
- Do not fabricate performance data.

## Working Tree Notes

Build directories may exist as untracked files:

```text
build-hb/
build-native/
```

Do not commit build directories or generated benchmark outputs unless the user
explicitly requests it.

## Last Session

This session added:

- `AGENTS.md`
- this handoff file
- a status entry in `hb_integration_status.md`

No source code behavior was changed in this session.

