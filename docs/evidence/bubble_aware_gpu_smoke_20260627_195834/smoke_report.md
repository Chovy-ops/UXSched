# Bubble-Aware GPU Smoke Report

Status: **PASS**

## Positive Execution Tests

- `case_off`
- `case_explicit_open`
- `case_hp_active`

These cases execute real LP work and require `correctness_status=PASS`.

## Expected-Deferred Safety Tests

- `case_no_hint`
- `case_fail_safe`

These cases intentionally do not execute the LP kernel. They verify that no Hummingbird child launch, no Native LP fallback, no crash, and no timeout occur when the bubble gate rejects work. Their correctness status is `NOT_APPLICABLE`.

All gate checks passed.
