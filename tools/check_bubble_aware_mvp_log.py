#!/usr/bin/env python3
"""Check conservative bubble-aware MVP event logs.

The checker consumes stderr/stdout logs containing [UXSCHED-BUBBLE] event lines
and verifies the minimal safety invariants. It does not require a GPU and does
not infer performance.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


KV_RE = re.compile(r"([A-Za-z0-9_]+)=([^ ]+)")


def parse_line(line: str) -> dict[str, str] | None:
    if "[UXSCHED-BUBBLE]" not in line:
        return None
    return {key: value for key, value in KV_RE.findall(line)}


def load_events(paths: list[Path]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for path in paths:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parsed = parse_line(line)
                if parsed is not None:
                    parsed["_source"] = str(path)
                    events.append(parsed)
    return events


def as_int(event: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(event.get(key, str(default)), 0)
    except ValueError:
        return default


def check_events(events: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    names = [event.get("event") for event in events]

    required = ["bubble_open", "bubble_close", "lp_child_launch_in_bubble", "hp_enqueue"]
    for name in required:
        if name not in names:
            errors.append(f"missing event={name}")

    hp_active = False
    for event in events:
        name = event.get("event")
        if name == "hp_enqueue":
            hp_active = True
        elif name == "hp_queue_empty":
            hp_active = False
        elif hp_active and name == "lp_child_launch_in_bubble":
            errors.append(
                "LP child launch observed while HP pending "
                f"source={event.get('_source')} parent={event.get('parent_launch_id')}"
            )

        if as_int(event, "lp_in_flight") > 1:
            errors.append(
                "lp_in_flight exceeded threshold "
                f"value={event.get('lp_in_flight')} source={event.get('_source')}"
            )

    stats = [event for event in events if event.get("bubble_stats")]
    for event in events:
        if "max_lp_in_flight" in event and as_int(event, "max_lp_in_flight") > 1:
            errors.append(f"max_lp_in_flight exceeded 1 in {event.get('_source')}")

    if not stats and not any("max_lp_in_flight" in event for event in events):
        errors.append("missing bubble_stats or max_lp_in_flight summary")

    return errors


def run_self_test() -> int:
    sample = [
        "[UXSCHED-BUBBLE] event=bubble_open lp_in_flight=0",
        "[UXSCHED-BUBBLE] event=lp_child_launch_in_bubble lp_in_flight=1",
        "[UXSCHED-BUBBLE] event=lp_child_complete lp_in_flight=0",
        "[UXSCHED-BUBBLE] event=bubble_close lp_in_flight=0",
        "[UXSCHED-BUBBLE] event=hp_enqueue lp_in_flight=0",
        "[UXSCHED-BUBBLE] event=hp_queue_empty lp_in_flight=0",
        "[UXSCHED-BUBBLE] bubble_stats max_lp_in_flight=1",
    ]
    events = [parse_line(line) or {} for line in sample]
    errors = check_events(events)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    bad = [
        "[UXSCHED-BUBBLE] event=bubble_open lp_in_flight=0",
        "[UXSCHED-BUBBLE] event=hp_enqueue lp_in_flight=0",
        "[UXSCHED-BUBBLE] event=lp_child_launch_in_bubble lp_in_flight=1",
        "[UXSCHED-BUBBLE] bubble_stats max_lp_in_flight=1",
    ]
    bad_events = [parse_line(line) or {} for line in bad]
    if not check_events(bad_events):
        print("self-test failed to reject LP launch while HP pending", file=sys.stderr)
        return 1

    print("bubble_aware_log_checker_selftest=PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="*", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if not args.logs:
        parser.error("at least one log path is required unless --self-test is used")

    events = load_events(args.logs)
    errors = check_events(events)
    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(f"bubble_aware_log_check=PASS event_count={len(events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
