# UXSched Agent Rules

## UXSched-Hummingbird Integration Rules

### Project Paths

- UXSched: `/home/zm/project/UXSched`
- Hummingbird: `/home/zm/project/hummingbird`
- Python environment: `/home/zm/project/hummingbird/.venv`

### Architecture Invariants

1. UXSched is the only global scheduler.
2. UXSched CUDA shim is the only CUDA hook entry.
3. Do not use two CUDA `LD_PRELOAD` hook libraries.
4. Hummingbird is integrated as a CUDA runtime strategy inside UXSched.
5. Do not start an independent Hummingbird scheduler.
6. UXSched decides which XQueue may run.
7. Hummingbird Runtime only controls fine-grained execution of eligible LP kernels.
8. HP kernels always use passthrough and are never split.
9. Unsupported LP kernels must safely fall back to UXSched Native.
10. `/home/zm/project/hummingbird` is read-only unless the user explicitly changes this rule.

### Runtime Strategies

- `NATIVE`: original UXSched behavior.
- `HB_FIXED`: fixed-size LP splitting.
- `HB_RUNTIME`: future full Hummingbird runtime.
- `AUTO`: future capability-aware selection.

Currently, only `NATIVE` and `HB_FIXED` have implementation paths. `HB_RUNTIME`
and `AUTO` must not be described as complete until runtime validation proves
otherwise.

### Validation Rules

Use the following statuses precisely:

- IMPLEMENTED
- COMPILE VERIFIED
- RUNTIME VERIFIED
- CORRECTNESS VERIFIED
- GLOBAL SCHEDULING VERIFIED
- PERFORMANCE VERIFIED
- NOT TESTED
- BLOCKED
- FAILED

Compilation success is not runtime verification.

A feature cannot be marked correctness verified without real GPU execution and
output validation.

Do not fabricate performance data.

### Development Gates

Gate 1 must pass before implementing the complete runtime:

- HB_FIXED executes on a real GPU.
- LP produces more than one real split launch.
- The transformed CUfunction is actually submitted.
- Native and HB_FIXED checksums match.
- HP passthrough is verified.
- Native fallback is verified.
- Event, stream, context/device synchronization semantics are correct.
- Global Lv1 HPF smoke test passes without local fallback.

### Git Rules

- Work on `feature/hummingbird-split-backend`.
- Inspect `git status`, current branch, and recent commits before changes.
- Keep commits small and independently buildable.
- Do not commit build directories or generated benchmark outputs unless
  explicitly requested.
- Update `hb_integration_status.md` and `docs/codex_handoff.md` before ending a
  work session.

