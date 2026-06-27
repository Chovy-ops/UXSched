#!/usr/bin/env python3
"""Aggregate and gate-check real CUDA bubble-aware smoke results."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
from pathlib import Path


KV_RE = re.compile(r"([A-Za-z0-9_]+)=([^ ]+)")

SUMMARY_FIELDS = [
    "case",
    "status",
    "correctness_pass",
    "correctness_status",
    "expected_deferred_pass",
    "bubble_aware_enabled",
    "bubble_hint_mode",
    "bubble_open_count",
    "bubble_close_count",
    "bubble_fill_attempt_count",
    "bubble_fill_success_count",
    "bubble_fill_rejected_count",
    "bubble_reject_hp_pending_count",
    "bubble_reject_no_hint_count",
    "lp_child_launched_in_bubble_count",
    "lp_child_complete_count",
    "stop_new_lp_on_hp_count",
    "max_lp_in_flight",
    "final_lp_in_flight",
    "bubble_fail_safe_count",
    "hp_hb_transform_count",
    "hb_parent_launch_count",
    "hb_child_launch_count",
    "hb_fallback_count",
    "hb_no_xqueue_count",
    "native_lp_launch_count",
    "native_lp_launch_during_hp_window",
    "hp_passthrough_launch_count",
    "global_scheduler_log_pass",
    "local_fallback_count",
    "event_order_pass",
    "first_lp_child_before_hp_enqueue",
    "lp_child_event_role_pass",
]


def parse_kv_line(line: str) -> dict[str, str]:
    return {key: value for key, value in KV_RE.findall(line)}


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def load_output_json(case_dir: Path) -> dict[str, object]:
    output = case_dir / "output.jsonl"
    if not output.exists():
        return {}
    last: dict[str, object] = {}
    with output.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def load_status(case_dir: Path) -> str:
    status_file = case_dir / "status.env"
    if not status_file.exists():
        return "UNKNOWN"
    for line in status_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("status="):
            return line.split("=", 1)[1]
    return "UNKNOWN"


def int_value(row: dict[str, object], key: str, default: int = 0) -> int:
    try:
        return int(str(row.get(key, default)), 0)
    except ValueError:
        return default


def bool_value(value: object) -> int:
    return 1 if value is True or str(value).lower() in {"1", "true", "yes", "on"} else 0


def event_between_hp_window(events: list[dict[str, str]]) -> bool:
    hp_active = False
    ok = True
    for event in events:
        name = event.get("event")
        if name == "hp_enqueue":
            hp_active = True
        elif name == "hp_queue_empty":
            hp_active = False
        elif hp_active and name == "lp_child_launch_in_bubble":
            ok = False
    return ok


def first_lp_child_before_hp_enqueue(events: list[dict[str, str]]) -> bool:
    first_child = None
    first_hp = None
    for idx, event in enumerate(events):
        if event.get("event") == "lp_child_launch_in_bubble" and first_child is None:
            first_child = idx
        if event.get("event") == "hp_enqueue" and first_hp is None:
            first_hp = idx
    return first_child is not None and first_hp is not None and first_child < first_hp


def lp_child_events_have_lp_role(events: list[dict[str, str]]) -> bool:
    for event in events:
        if event.get("event") in {
            "bubble_fill_attempt",
            "bubble_fill_rejected",
            "lp_child_launch_in_bubble",
            "lp_child_complete",
        }:
            if event.get("task_role") != "LP" or event.get("task_priority") != "-10":
                return False
    return True


def native_lp_between_hp_window(lines: list[str]) -> int:
    hp_active = False
    count = 0
    for line in lines:
        if "[UXSCHED-BUBBLE]" in line and "event=hp_enqueue" in line:
            hp_active = True
        elif "[UXSCHED-BUBBLE]" in line and "event=hp_queue_empty" in line:
            hp_active = False
        elif hp_active and (
            ("runtime_launch_fallback" in line and "task_role=LP" in line and "is_fallback=1" in line)
            or (
                "backend_selected=NATIVE" in line
                and "task_role=LP" in line
                and "is_fallback=1" in line
            )
        ):
            count += 1
    return count


def collect_case(result_dir: Path, case: str) -> dict[str, object]:
    case_dir = result_dir / case
    stdout = read_text(case_dir / "stdout.log")
    stderr = read_text(case_dir / "stderr.log")
    combined = stdout + "\n" + stderr
    lines = combined.splitlines()
    output = load_output_json(case_dir)

    events: list[dict[str, str]] = []
    stats_line: dict[str, str] = {}
    for line in lines:
        if "[UXSCHED-BUBBLE]" not in line:
            continue
        parsed = parse_kv_line(line)
        if "event" in parsed:
            events.append(parsed)
        if "bubble_stats" in line:
            stats_line = parsed

    with (case_dir / "bubble_events.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def count(pattern: str) -> int:
        return len(re.findall(pattern, combined))

    shell_status = load_status(case_dir)
    output_status = str(output.get("status", ""))
    expected_deferred_candidate = case in {"case_no_hint", "case_fail_safe"}

    stats: dict[str, object] = {
        "case": case,
        "status": output_status if output_status == "EXPECTED_DEFERRED" else shell_status,
        "correctness_pass": bool_value(output.get("correctness_pass")),
        "correctness_status": "PASS" if bool_value(output.get("correctness_pass")) else "FAIL",
        "expected_deferred_pass": 0,
        "bubble_aware_enabled": int(stats_line.get("bubble_aware_enabled", "0")),
        "bubble_hint_mode": stats_line.get("bubble_hint_mode", "explicit" if events else "none"),
        "bubble_open_count": int(stats_line.get("bubble_open_count", "0")),
        "bubble_close_count": int(stats_line.get("bubble_close_count", "0")),
        "bubble_fill_attempt_count": int(stats_line.get("bubble_fill_attempt_count", "0")),
        "bubble_fill_success_count": int(stats_line.get("bubble_fill_success_count", "0")),
        "bubble_fill_rejected_count": int(stats_line.get("bubble_fill_rejected_count", "0")),
        "bubble_reject_hp_pending_count": int(stats_line.get("bubble_reject_hp_pending_count", "0")),
        "bubble_reject_no_hint_count": int(stats_line.get("bubble_reject_no_hint_count", "0")),
        "lp_child_launched_in_bubble_count": int(
            stats_line.get("lp_child_launched_in_bubble_count", "0")
        ),
        "lp_child_complete_count": sum(1 for event in events if event.get("event") == "lp_child_complete"),
        "stop_new_lp_on_hp_count": int(stats_line.get("stop_new_lp_on_hp_count", "0")),
        "max_lp_in_flight": int(stats_line.get("max_lp_in_flight", "0")),
        "final_lp_in_flight": int(stats_line.get("lp_in_flight", "0")),
        "bubble_fail_safe_count": int(stats_line.get("bubble_fail_safe_count", "0")),
        "hp_hb_transform_count": count(r"\[UXSCHED-HB\].*transform_succeeded.*priority=10"),
        "hb_parent_launch_count": count(r"\[UXSCHED-HB\].*parent_launch_submitted"),
        "hb_child_launch_count": count(r"\[UXSCHED-HB\].*child_launch_submitted"),
        "hb_fallback_count": count(r"\[UXSCHED-HB\].*backend_selected=NATIVE.*is_fallback=1"),
        "hb_no_xqueue_count": count(r"\[UXSCHED-HB\].*reason=NO_XQUEUE"),
        "native_lp_launch_count": count(
            r"\[UXSCHED-CUDART\].*runtime_launch_fallback.*task_role=LP.*is_fallback=1"
        )
        + count(r"\[UXSCHED-HB\].*backend_selected=NATIVE.*task_role=LP.*is_fallback=1"),
        "native_lp_launch_during_hp_window": native_lp_between_hp_window(lines),
        "hp_passthrough_launch_count": count(
            r"\[UXSCHED-CUDART\].*runtime_launch_passthrough.*task_role=HP.*is_fallback=0"
        ),
        "global_scheduler_log_pass": 0,
        "local_fallback_count": count(r"using local scheduler|local scheduler fallback"),
        "event_order_pass": 1 if event_between_hp_window(events) else 0,
        "first_lp_child_before_hp_enqueue": 1 if first_lp_child_before_hp_enqueue(events) else 0,
        "lp_child_event_role_pass": 1 if lp_child_events_have_lp_role(events) else 0,
    }

    if expected_deferred_candidate:
        deferred_pass = (
            stats["status"] != "TIMEOUT"
            and int(stats["lp_child_launched_in_bubble_count"]) == 0
            and int(stats["native_lp_launch_count"]) == 0
            and int(stats["hb_fallback_count"]) == 0
            and int(stats["local_fallback_count"]) == 0
            and (
                (case == "case_no_hint" and int(stats["bubble_reject_no_hint_count"]) > 0)
                or (case == "case_fail_safe" and int(stats["bubble_fail_safe_count"]) > 0)
            )
        )
        if deferred_pass:
            stats["status"] = "EXPECTED_DEFERRED"
            stats["expected_deferred_pass"] = 1
            stats["correctness_status"] = "NOT_APPLICABLE"

    xserver = read_text(result_dir / "xserver" / "stdout.log") + "\n" + read_text(
        result_dir / "xserver" / "stderr.log"
    )
    if "scheduler created with policy HPF" in xserver and (
        "client process connected" in xserver or count(r"using global scheduler") > 0
    ):
        stats["global_scheduler_log_pass"] = 1

    with (case_dir / "bubble_stats.env").open("w", encoding="utf-8") as handle:
        for key in SUMMARY_FIELDS:
            if key in stats:
                handle.write(f"{key}={stats[key]}\n")

    with (case_dir / "backend_stats.env").open("w", encoding="utf-8") as handle:
        for key in [
            "hp_hb_transform_count",
            "hb_parent_launch_count",
            "hb_child_launch_count",
            "hb_fallback_count",
            "hb_no_xqueue_count",
            "global_scheduler_log_pass",
            "local_fallback_count",
        ]:
            handle.write(f"{key}={stats[key]}\n")

    return stats


def gate(rows: dict[str, dict[str, object]]) -> tuple[bool, list[str]]:
    errors: list[str] = []

    def need(case: str, cond: bool, message: str) -> None:
        if not cond:
            errors.append(f"{case}: {message}")

    off = rows.get("case_off", {})
    need("case_off", str(off.get("status")) == "COMPLETE", "case did not complete")
    need("case_off", int_value(off, "correctness_pass") == 1, "correctness failed")
    need("case_off", int_value(off, "hb_parent_launch_count") > 0, "missing parent launch")
    need(
        "case_off",
        int_value(off, "hb_child_launch_count") > int_value(off, "hb_parent_launch_count"),
        "child count must exceed parent count",
    )
    need("case_off", int_value(off, "hp_hb_transform_count") == 0, "HP transformed")
    need("case_off", int_value(off, "hb_fallback_count") == 0, "fallback observed")
    need("case_off", int_value(off, "hb_no_xqueue_count") == 0, "NO_XQUEUE observed")
    need("case_off", int_value(off, "global_scheduler_log_pass") == 1, "global scheduler missing")
    need("case_off", int_value(off, "local_fallback_count") == 0, "local fallback observed")

    open_case = rows.get("case_explicit_open", {})
    need("case_explicit_open", str(open_case.get("status")) == "COMPLETE", "case did not complete")
    for key in [
        "correctness_pass",
        "bubble_open_count",
        "bubble_close_count",
        "bubble_fill_attempt_count",
        "bubble_fill_success_count",
        "lp_child_launched_in_bubble_count",
    ]:
        need("case_explicit_open", int_value(open_case, key) > 0, f"{key} not positive")
    need("case_explicit_open", int_value(open_case, "max_lp_in_flight") == 1, "max in-flight != 1")
    need("case_explicit_open", int_value(open_case, "final_lp_in_flight") == 0, "final in-flight != 0")
    need("case_explicit_open", int_value(open_case, "event_order_pass") == 1, "event order failed")
    need("case_explicit_open", int_value(open_case, "lp_child_event_role_pass") == 1,
         "LP child event role/priority mismatch")

    hp = rows.get("case_hp_active", {})
    need("case_hp_active", str(hp.get("status")) == "COMPLETE", "case did not complete")
    need("case_hp_active", int_value(hp, "correctness_pass") == 1, "correctness failed")
    need("case_hp_active", int_value(hp, "bubble_open_count") >= 2, "expected at least two bubble opens")
    need("case_hp_active", int_value(hp, "bubble_fill_success_count") > 0, "no bubble fill success")
    need("case_hp_active", int_value(hp, "lp_child_launched_in_bubble_count") > 0, "no LP child launch")
    need("case_hp_active", int_value(hp, "lp_child_complete_count") > 0, "no LP child completion")
    need(
        "case_hp_active",
        int_value(hp, "first_lp_child_before_hp_enqueue") == 1,
        "first LP child did not launch before HP enqueue",
    )
    need("case_hp_active", int_value(hp, "stop_new_lp_on_hp_count") > 0, "HP stop counter missing")
    need("case_hp_active", int_value(hp, "bubble_reject_hp_pending_count") > 0, "HP reject missing")
    need("case_hp_active", int_value(hp, "hp_passthrough_launch_count") > 0, "HP passthrough missing")
    need("case_hp_active", int_value(hp, "hp_hb_transform_count") == 0, "HP transformed")
    need("case_hp_active", int_value(hp, "event_order_pass") == 1, "LP launch during HP window")
    need("case_hp_active", int_value(hp, "lp_child_event_role_pass") == 1,
         "LP child event role/priority mismatch")
    need(
        "case_hp_active",
        int_value(hp, "native_lp_launch_during_hp_window") == 0,
        "Native LP launch during HP window",
    )
    need("case_hp_active", int_value(hp, "max_lp_in_flight") <= 1, "max in-flight exceeded 1")
    need("case_hp_active", int_value(hp, "final_lp_in_flight") == 0, "final in-flight != 0")
    need("case_hp_active", int_value(hp, "hb_parent_launch_count") > 0, "missing parent launch")
    need("case_hp_active", int_value(hp, "hb_child_launch_count") > 0, "missing child launch")
    need("case_hp_active", int_value(hp, "hb_fallback_count") == 0, "HB fallback observed")
    need("case_hp_active", int_value(hp, "hb_no_xqueue_count") == 0, "NO_XQUEUE observed")
    need("case_hp_active", int_value(hp, "global_scheduler_log_pass") == 1, "global scheduler missing")
    need("case_hp_active", int_value(hp, "local_fallback_count") == 0, "local fallback observed")

    no_hint = rows.get("case_no_hint", {})
    need("case_no_hint", str(no_hint.get("status")) == "EXPECTED_DEFERRED", "case not expected-deferred")
    need("case_no_hint", int_value(no_hint, "expected_deferred_pass") == 1, "expected-deferred gate failed")
    need("case_no_hint", str(no_hint.get("correctness_status")) == "NOT_APPLICABLE",
         "correctness status should be not applicable")
    need("case_no_hint", int_value(no_hint, "bubble_reject_no_hint_count") > 0, "no-hint reject missing")
    need("case_no_hint", int_value(no_hint, "lp_child_launched_in_bubble_count") == 0, "LP child launched")
    need("case_no_hint", int_value(no_hint, "native_lp_launch_count") == 0, "Native LP launch observed")
    need("case_no_hint", int_value(no_hint, "hb_fallback_count") == 0, "HB fallback observed")
    need("case_no_hint", int_value(no_hint, "local_fallback_count") == 0, "local fallback observed")

    fail = rows.get("case_fail_safe", {})
    need("case_fail_safe", str(fail.get("status")) == "EXPECTED_DEFERRED", "case not expected-deferred")
    need("case_fail_safe", int_value(fail, "expected_deferred_pass") == 1, "expected-deferred gate failed")
    need("case_fail_safe", str(fail.get("correctness_status")) == "NOT_APPLICABLE",
         "correctness status should be not applicable")
    need("case_fail_safe", int_value(fail, "bubble_fill_attempt_count") > 0, "fail-safe case did not run")
    need("case_fail_safe", int_value(fail, "bubble_fail_safe_count") > 0, "fail-safe counter missing")
    need("case_fail_safe", int_value(fail, "lp_child_launched_in_bubble_count") == 0, "LP child launched")
    need("case_fail_safe", int_value(fail, "native_lp_launch_count") == 0, "Native LP launch observed")

    return not errors, errors


def write_outputs(result_dir: Path, rows: list[dict[str, object]], errors: list[str]) -> None:
    with (result_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in SUMMARY_FIELDS})

    passed = not errors
    with (result_dir / "status.env").open("w", encoding="utf-8") as handle:
        handle.write(f"BUBBLE_AWARE_GPU_SMOKE={'PASS' if passed else 'FAIL'}\n")
        handle.write(f"case_count={len(rows)}\n")
        handle.write(f"error_count={len(errors)}\n")

    with (result_dir / "smoke_report.md").open("w", encoding="utf-8") as handle:
        handle.write("# Bubble-Aware GPU Smoke Report\n\n")
        handle.write(f"Status: **{'PASS' if passed else 'FAIL'}**\n\n")
        handle.write("## Positive Execution Tests\n\n")
        handle.write("- `case_off`\n")
        handle.write("- `case_explicit_open`\n")
        handle.write("- `case_hp_active`\n\n")
        handle.write("These cases execute real LP work and require `correctness_status=PASS`.\n\n")
        handle.write("## Expected-Deferred Safety Tests\n\n")
        handle.write("- `case_no_hint`\n")
        handle.write("- `case_fail_safe`\n\n")
        handle.write(
            "These cases intentionally do not execute the LP kernel. They verify that no "
            "Hummingbird child launch, no Native LP fallback, no crash, and no timeout "
            "occur when the bubble gate rejects work. Their correctness status is "
            "`NOT_APPLICABLE`.\n\n"
        )
        if errors:
            handle.write("## Gate Failures\n\n")
            for error in errors:
                handle.write(f"- {error}\n")
        else:
            handle.write("All gate checks passed.\n")


def run(result_dir: Path, emit_errors: bool = True) -> int:
    cases = ["case_off", "case_explicit_open", "case_hp_active", "case_no_hint", "case_fail_safe"]
    rows = [collect_case(result_dir, case) for case in cases]
    by_case = {str(row["case"]): row for row in rows}
    passed, errors = gate(by_case)
    write_outputs(result_dir, rows, errors)
    if passed:
        print("BUBBLE_AWARE_GPU_SMOKE=PASS")
        return 0
    if emit_errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
    return 1


def summary_rows(result_dir: Path) -> dict[str, dict[str, str]]:
    with (result_dir / "summary.csv").open("r", encoding="utf-8", newline="") as handle:
        return {row["case"]: row for row in csv.DictReader(handle)}


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "xserver").mkdir()
        (root / "xserver" / "stdout.log").write_text(
            "scheduler created with policy HPF\nclient process connected\n",
            encoding="utf-8",
        )
        for case in ["case_off", "case_explicit_open", "case_hp_active", "case_no_hint", "case_fail_safe"]:
            d = root / case
            d.mkdir()
            (d / "status.env").write_text("status=COMPLETE\n", encoding="utf-8")
            if case in {"case_no_hint", "case_fail_safe"}:
                (d / "output.jsonl").write_text(
                    '{"status":"EXPECTED_DEFERRED","correctness_pass":false}\n',
                    encoding="utf-8",
                )
            else:
                (d / "output.jsonl").write_text(
                    '{"status":"RAN","correctness_pass":true}\n',
                    encoding="utf-8",
                )
            stderr = []
            if case == "case_off":
                stderr += [
                    "[UXSCHED-HB] parent_launch_submitted",
                    "[UXSCHED-HB] child_launch_submitted",
                    "[UXSCHED-HB] child_launch_submitted",
                ]
            elif case == "case_explicit_open":
                stderr += [
                    "[UXSCHED-BUBBLE] event=bubble_open task_role=HP task_priority=0 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=bubble_fill_attempt task_role=LP task_priority=-10 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=lp_child_launch_in_bubble task_role=LP task_priority=-10 lp_in_flight=1",
                    "[UXSCHED-BUBBLE] event=lp_child_complete task_role=LP task_priority=-10 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=bubble_close task_role=HP task_priority=0 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] bubble_stats bubble_aware_enabled=1 bubble_hint_mode=explicit "
                    "bubble_open_count=1 bubble_close_count=1 bubble_fill_attempt_count=1 "
                    "bubble_fill_success_count=1 bubble_fill_rejected_count=0 "
                    "bubble_reject_hp_pending_count=0 bubble_reject_no_hint_count=0 "
                    "lp_child_launched_in_bubble_count=1 stop_new_lp_on_hp_count=0 "
                    "max_lp_in_flight=1 bubble_fail_safe_count=0 lp_in_flight=0",
                ]
            elif case == "case_hp_active":
                stderr += [
                    "[UXSCHED-BUBBLE] event=bubble_open task_role=HP task_priority=0 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=bubble_fill_attempt task_role=LP task_priority=-10 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=lp_child_launch_in_bubble task_role=LP task_priority=-10 lp_in_flight=1",
                    "[UXSCHED-BUBBLE] event=hp_enqueue task_role=HP task_priority=10 lp_in_flight=1",
                    "[UXSCHED-CUDART] runtime_launch_passthrough backend=NATIVE task_role=HP priority=10 is_fallback=0",
                    "[UXSCHED-HB] backend_selected=NATIVE reason=HIGH_PRIORITY_PASSTHROUGH task_role=HP task_priority=10 is_fallback=0",
                    "[UXSCHED-BUBBLE] event=bubble_fill_rejected task_role=LP task_priority=-10 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=lp_child_complete task_role=LP task_priority=-10 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=hp_queue_empty task_role=HP task_priority=10 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=bubble_open task_role=HP task_priority=0 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] event=lp_child_launch_in_bubble task_role=LP task_priority=-10 lp_in_flight=1",
                    "[UXSCHED-BUBBLE] event=lp_child_complete task_role=LP task_priority=-10 lp_in_flight=0",
                    "[UXSCHED-HB] parent_launch_submitted",
                    "[UXSCHED-HB] child_launch_submitted",
                    "[UXSCHED-BUBBLE] bubble_stats bubble_aware_enabled=1 bubble_hint_mode=explicit "
                    "bubble_open_count=3 bubble_close_count=1 bubble_fill_attempt_count=3 "
                    "bubble_fill_success_count=2 bubble_fill_rejected_count=1 "
                    "bubble_reject_hp_pending_count=1 bubble_reject_no_hint_count=0 "
                    "lp_child_launched_in_bubble_count=2 stop_new_lp_on_hp_count=1 "
                    "max_lp_in_flight=1 bubble_fail_safe_count=0 lp_in_flight=0",
                ]
            elif case == "case_no_hint":
                stderr += [
                    "[UXSCHED-BUBBLE] event=bubble_fill_rejected task_role=LP task_priority=-10 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] bubble_stats bubble_aware_enabled=1 bubble_hint_mode=explicit "
                    "bubble_open_count=0 bubble_close_count=0 bubble_fill_attempt_count=1 "
                    "bubble_fill_success_count=0 bubble_fill_rejected_count=1 "
                    "bubble_reject_hp_pending_count=0 bubble_reject_no_hint_count=1 "
                    "lp_child_launched_in_bubble_count=0 stop_new_lp_on_hp_count=0 "
                    "max_lp_in_flight=0 bubble_fail_safe_count=0 lp_in_flight=0",
                ]
            else:
                stderr += [
                    "[UXSCHED-BUBBLE] event=bubble_fill_rejected task_role=LP task_priority=-10 lp_in_flight=0",
                    "[UXSCHED-BUBBLE] bubble_stats bubble_aware_enabled=1 bubble_hint_mode=explicit "
                    "bubble_open_count=0 bubble_close_count=2 bubble_fill_attempt_count=1 "
                    "bubble_fill_success_count=0 bubble_fill_rejected_count=1 "
                    "bubble_reject_hp_pending_count=0 bubble_reject_no_hint_count=1 "
                    "lp_child_launched_in_bubble_count=0 stop_new_lp_on_hp_count=0 "
                    "max_lp_in_flight=0 bubble_fail_safe_count=1 lp_in_flight=0",
                ]
            (d / "stderr.log").write_text("\n".join(stderr) + "\n", encoding="utf-8")
            (d / "stdout.log").write_text("", encoding="utf-8")
        rc = run(root)
        if rc != 0:
            return rc
        rows = summary_rows(root)
        if rows["case_hp_active"].get("hp_passthrough_launch_count") != "1":
            print("self-test failed to de-duplicate HP passthrough", file=sys.stderr)
            return 1
        if rows["case_no_hint"].get("expected_deferred_pass") != "1":
            print("self-test failed no-hint expected-deferred status", file=sys.stderr)
            return 1
        if rows["case_fail_safe"].get("correctness_status") != "NOT_APPLICABLE":
            print("self-test failed fail-safe correctness status", file=sys.stderr)
            return 1

        hp_passthrough = parse_kv_line(
            "[UXSCHED-CUDART] runtime_launch_passthrough backend=NATIVE "
            "task_role=HP priority=10 is_fallback=0"
        )
        lp_fallback = parse_kv_line(
            "[UXSCHED-CUDART] runtime_launch_fallback backend=NATIVE "
            "task_role=LP priority=-10 is_fallback=1"
        )
        if "task_role" not in hp_passthrough or hp_passthrough.get("is_fallback") != "0":
            print("self-test failed HP passthrough parse", file=sys.stderr)
            return 1
        if "task_role" not in lp_fallback or lp_fallback.get("is_fallback") != "1":
            print("self-test failed LP fallback parse", file=sys.stderr)
            return 1

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "xserver").mkdir()
        (root / "xserver" / "stdout.log").write_text(
            "scheduler created with policy HPF\nclient process connected\n",
            encoding="utf-8",
        )
        for case in ["case_off", "case_explicit_open", "case_hp_active", "case_no_hint", "case_fail_safe"]:
            d = root / case
            d.mkdir()
            (d / "status.env").write_text("status=COMPLETE\n", encoding="utf-8")
            (d / "output.jsonl").write_text(
                '{"status":"EXPECTED_DEFERRED","correctness_pass":false}\n'
                if case in {"case_no_hint", "case_fail_safe"}
                else '{"status":"RAN","correctness_pass":true}\n',
                encoding="utf-8",
            )
            if case == "case_no_hint":
                stderr = (
                    "[UXSCHED-BUBBLE] event=bubble_fill_rejected task_role=LP task_priority=-10 lp_in_flight=0\n"
                    "[UXSCHED-CUDART] runtime_launch_fallback backend=NATIVE task_role=LP priority=-10 is_fallback=1\n"
                    "[UXSCHED-BUBBLE] bubble_stats bubble_aware_enabled=1 bubble_hint_mode=explicit "
                    "bubble_open_count=0 bubble_close_count=0 bubble_fill_attempt_count=1 "
                    "bubble_fill_success_count=0 bubble_fill_rejected_count=1 "
                    "bubble_reject_hp_pending_count=0 bubble_reject_no_hint_count=1 "
                    "lp_child_launched_in_bubble_count=0 stop_new_lp_on_hp_count=0 "
                    "max_lp_in_flight=0 bubble_fail_safe_count=0 lp_in_flight=0\n"
                )
            else:
                stderr = ""
            (d / "stderr.log").write_text(stderr, encoding="utf-8")
            (d / "stdout.log").write_text("", encoding="utf-8")
        if run(root, emit_errors=False) == 0:
            print("self-test failed to reject Native LP fallback in expected-deferred case", file=sys.stderr)
            return 1

        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.result_dir is None:
        parser.error("--result-dir is required unless --self-test is used")
    return run(args.result_dir)


if __name__ == "__main__":
    raise SystemExit(main())
