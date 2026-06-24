#!/usr/bin/env python3
"""Run reproducible RTX4060 XSched preemption experiments.

This script intentionally does not modify platforms/RTX4060/test/resnet152_full.py.
It starts standard worker tasks in separate processes, staggers low/high priority
starts, parses throughput lines, and writes CSV/JSON artifacts for reports.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_LIB = ROOT / "output/lib"
XSERVER = ROOT / "output/bin/xserver"
XCLI = ROOT / "output/bin/xcli"
RESULTS = ROOT / "benchmark_results"
DEFAULT_REAL_LIBCUDA = "/usr/lib/wsl/lib/libcuda.so.1"
THPT_RE = re.compile(r"thpt:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z0-9_/]+)")
WORKLOADS = ("cnn", "transformer", "train")


@dataclass
class ProcSpec:
    role: str
    workload: str
    priority: int
    index: int
    proc: subprocess.Popen[str]
    log_file: TextIO
    start_elapsed_s: float
    first_thpt_elapsed_s: float | None = None
    records: list[dict[str, object]] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Launch low/high priority standard GPU tasks and record XSched preemption throughput."
    )
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--workload", choices=WORKLOADS, default="cnn", help=argparse.SUPPRESS)
    p.add_argument("--role", default="worker", help=argparse.SUPPRESS)
    p.add_argument("--mode", choices=["xsched", "native"], default="xsched",
                   help="xsched uses GLB/HPF; native runs without XSched env.")
    p.add_argument("--lp-workload", choices=WORKLOADS, default="train",
                   help="Low-priority workload: cnn=ResNet50 infer, transformer=infer, train=MobileNetV2 train.")
    p.add_argument("--hp-workload", choices=WORKLOADS, default="cnn",
                   help="High-priority workload: cnn=ResNet50 infer, transformer=infer, train=MobileNetV2 train.")
    p.add_argument("--lp-count", type=int, default=1,
                   help="Number of low-priority processes to start before HP.")
    p.add_argument("--hp-count", type=int, default=1,
                   help="Number of high-priority processes to start after --hp-delay.")
    p.add_argument("--hp-delay", type=float, default=20.0,
                   help="Seconds to let LP run before starting HP.")
    p.add_argument("--duration-after-hp", type=float, default=40.0,
                   help="Seconds to keep collecting after HP starts.")
    p.add_argument("-c", "--run-cnt", type=int, default=10,
                   help="Iterations per throughput round inside each worker.")
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--transformer-batch-size", type=int, default=8)
    p.add_argument("--train-batch-size", type=int, default=16)
    p.add_argument("--image-size", type=int, default=224)
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--xqueue-level", type=int, default=1)
    p.add_argument("--threshold", type=int, default=16)
    p.add_argument("--batch-commands", type=int, default=8)
    p.add_argument("--policy", default="HPF")
    p.add_argument("--port", type=int, default=50000)
    p.add_argument("--real-libcuda", default=DEFAULT_REAL_LIBCUDA)
    p.add_argument("--result-dir", type=Path, default=None)
    p.add_argument("--no-start-xserver", action="store_true",
                   help="Require an existing xserver instead of starting one.")
    p.add_argument("--restart-xserver", action="store_true",
                   help="Stop existing output/bin/xserver processes before starting a fresh one.")
    p.add_argument("--python", default=sys.executable)
    return p.parse_args()


def make_result_dir(user_dir: Path | None) -> Path:
    if user_dir is not None:
        out = user_dir
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out = RESULTS / f"rtx4060_resnet_preempt_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def prepend_path(value: str, prefix: Path) -> str:
    old = value or ""
    return f"{prefix}:{old}" if old else str(prefix)


def child_env(args: argparse.Namespace, priority: int) -> dict[str, str]:
    env = os.environ.copy()
    if args.mode == "native":
        for key in list(env):
            if key.startswith("XSCHED_") or key == "CUXTRA_CUDA_LIB":
                env.pop(key, None)
        env.pop("LD_PRELOAD", None)
        if "LD_LIBRARY_PATH" in env:
            paths = [p for p in env["LD_LIBRARY_PATH"].split(":") if p != str(OUTPUT_LIB)]
            env["LD_LIBRARY_PATH"] = ":".join(paths)
        return env

    env["XSCHED_CUDA_LIB"] = args.real_libcuda
    env["CUXTRA_CUDA_LIB"] = args.real_libcuda
    env["LD_LIBRARY_PATH"] = prepend_path(env.get("LD_LIBRARY_PATH", ""), OUTPUT_LIB)
    env.pop("LD_PRELOAD", None)
    env.setdefault("XLOG_LEVEL", "INFO")
    env["XSCHED_SCHEDULER"] = "GLB"
    env["XSCHED_AUTO_XQUEUE"] = "ON"
    env["XSCHED_AUTO_XQUEUE_PRIORITY"] = str(priority)
    env["XSCHED_AUTO_XQUEUE_LEVEL"] = str(args.xqueue_level)
    env["XSCHED_AUTO_XQUEUE_THRESHOLD"] = str(args.threshold)
    env["XSCHED_AUTO_XQUEUE_BATCH_SIZE"] = str(args.batch_commands)
    return env


def check_xserver(args: argparse.Namespace) -> bool:
    try:
        res = subprocess.run(
            [str(XCLI), "--port", str(args.port), "policy", "-q"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
            check=False,
        )
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def stop_existing_xserver() -> None:
    try:
        res = subprocess.run(
            ["pgrep", "-f", str(XSERVER)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return
    pids = [int(line) for line in res.stdout.splitlines() if line.strip().isdigit()]
    for pid in pids:
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.time() + 3.0
    while time.time() < deadline:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        if not alive:
            return
        time.sleep(0.1)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def start_xserver(args: argparse.Namespace, result_dir: Path) -> subprocess.Popen[str] | None:
    if args.mode != "xsched":
        return None
    if args.restart_xserver:
        stop_existing_xserver()
    if check_xserver(args):
        return None
    if args.no_start_xserver:
        raise RuntimeError("xserver is not responding; start output/bin/xserver first")

    log = (result_dir / "xserver.log").open("w", buffering=1)
    env = os.environ.copy()
    env.setdefault("XLOG_LEVEL", "INFO")
    proc = subprocess.Popen(
        [str(XSERVER), args.policy, str(args.port)],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"xserver exited early with code {proc.returncode}")
        if check_xserver(args):
            return proc
        time.sleep(0.1)
    raise RuntimeError("xserver did not become ready within 5 seconds")


def worker_batch_size(args: argparse.Namespace, workload: str) -> int:
    if workload == "transformer":
        return args.transformer_batch_size
    if workload == "train":
        return args.train_batch_size
    return args.batch_size


def bench_cmd(args: argparse.Namespace, role: str, workload: str) -> list[str]:
    return [
        args.python,
        str(Path(__file__).resolve()),
        "--worker",
        "--role",
        role,
        "--workload",
        workload,
        "-c",
        str(args.run_cnt),
        "--gpu",
        str(args.gpu),
        "--batch-size",
        str(worker_batch_size(args, workload)),
        "--image-size",
        str(args.image_size),
        "--warmup",
        str(args.warmup),
    ]


def stream_output(spec: ProcSpec, t0: float, csv_rows: list[dict[str, object]],
                  rows_lock: threading.Lock) -> None:
    assert spec.proc.stdout is not None
    for line in spec.proc.stdout:
        spec.log_file.write(line)
        match = THPT_RE.search(line)
        if not match:
            continue
        row = {
            "elapsed_s": round(time.time() - t0, 3),
            "role": spec.role,
            "workload": spec.workload,
            "index": spec.index,
            "priority": spec.priority,
            "pid": spec.proc.pid,
            "throughput": float(match.group(1)),
            "unit": match.group(2),
        }
        if spec.first_thpt_elapsed_s is None:
            spec.first_thpt_elapsed_s = float(row["elapsed_s"])
        spec.records.append(row)
        with rows_lock:
            csv_rows.append(row)
        print(
            f"{row['elapsed_s']:>7.3f}s {spec.role}[{spec.index}] "
            f"{spec.workload} prio={spec.priority} pid={spec.proc.pid} "
            f"thpt={row['throughput']:.2f} {row['unit']}",
            flush=True,
        )


def launch_role(args: argparse.Namespace, role: str, workload: str, priority: int, index: int,
                result_dir: Path, t0: float, csv_rows: list[dict[str, object]],
                rows_lock: threading.Lock) -> tuple[ProcSpec, threading.Thread]:
    log_path = result_dir / f"{role}_{workload}_{index}.log"
    log_file = log_path.open("w", buffering=1)
    proc = subprocess.Popen(
        bench_cmd(args, role, workload),
        cwd=ROOT,
        env=child_env(args, priority),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    start_elapsed_s = round(time.time() - t0, 3)
    spec = ProcSpec(role=role, workload=workload, priority=priority, index=index,
                    proc=proc, log_file=log_file, start_elapsed_s=start_elapsed_s)
    thread = threading.Thread(target=stream_output, args=(spec, t0, csv_rows, rows_lock),
                              daemon=True)
    thread.start()
    print(f"started {role}[{index}] workload={workload} priority={priority} pid={proc.pid}",
          flush=True)
    return spec, thread


def terminate_proc(proc: subprocess.Popen[str], timeout: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=timeout)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["elapsed_s", "role", "workload", "index", "priority", "pid",
                        "throughput", "unit"],
        )
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: float(r["elapsed_s"])))


def summarize(specs: list[ProcSpec]) -> list[dict[str, object]]:
    summary = []
    for spec in specs:
        vals = [float(r["throughput"]) for r in spec.records]
        unit = spec.records[-1]["unit"] if spec.records else "samples/s"
        if vals:
            avg = sum(vals) / len(vals)
            last = vals[-1]
            peak = max(vals)
        else:
            avg = last = peak = 0.0
        if spec.first_thpt_elapsed_s is None:
            first_thpt_delay_s = None
        else:
            first_thpt_delay_s = round(spec.first_thpt_elapsed_s - spec.start_elapsed_s, 3)
        hp_wait_block_time_s = first_thpt_delay_s if spec.role == "hp" else None
        summary.append({
            "role": spec.role,
            "workload": spec.workload,
            "index": spec.index,
            "priority": spec.priority,
            "pid": spec.proc.pid,
            "start_elapsed_s": spec.start_elapsed_s,
            "first_thpt_elapsed_s": spec.first_thpt_elapsed_s,
            "first_thpt_delay_s": first_thpt_delay_s,
            "hp_wait_block_time_s": hp_wait_block_time_s,
            "samples": len(vals),
            "unit": unit,
            "avg_throughput": round(avg, 3),
            "last_throughput": round(last, 3),
            "peak_throughput": round(peak, 3),
            "returncode": spec.proc.returncode,
        })
    return summary


def check_cuda(gpu: int):
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available")
    if gpu < 0 or gpu >= torch.cuda.device_count():
        raise RuntimeError(f"invalid GPU {gpu}; visible device count is {torch.cuda.device_count()}")
    return torch.device(f"cuda:{gpu}")


def dedicated_stream(device):
    import torch

    stream = torch.cuda.Stream(device=device)
    torch.cuda.set_stream(stream)
    return stream


def worker_loop(args: argparse.Namespace) -> int:
    import torch
    import torchvision

    device = check_cuda(args.gpu)
    stream = dedicated_stream(device)
    torch.backends.cudnn.benchmark = True

    print(f"Worker: role={args.role} workload={args.workload} device={device} "
          f"batch={args.batch_size} run_cnt={args.run_cnt}", flush=True)
    if os.environ.get("XSCHED_AUTO_XQUEUE", "").upper() == "ON":
        print("XSched: transparent mode "
              f"(scheduler={os.environ.get('XSCHED_SCHEDULER', 'GLB')}, "
              f"priority={os.environ.get('XSCHED_AUTO_XQUEUE_PRIORITY', '0')}, "
              f"level={os.environ.get('XSCHED_AUTO_XQUEUE_LEVEL', '1')})",
              flush=True)

    if args.workload == "cnn":
        model = torchvision.models.resnet50(weights=None).eval().to(device)
        data = torch.ones(args.batch_size, 3, args.image_size, args.image_size, device=device)
        unit = "samples/s"

        def step() -> None:
            with torch.no_grad(), torch.cuda.stream(stream):
                model(data)

    elif args.workload == "transformer":
        layer = torch.nn.TransformerEncoderLayer(
            d_model=768,
            nhead=12,
            dim_feedforward=3072,
            batch_first=True,
            dropout=0.0,
            activation="gelu",
        )
        model = torch.nn.TransformerEncoder(layer, num_layers=6).eval().to(device)
        data = torch.randn(args.batch_size, 128, 768, device=device)
        unit = "samples/s"

        def step() -> None:
            with torch.no_grad(), torch.cuda.stream(stream):
                model(data)

    elif args.workload == "train":
        model = torchvision.models.mobilenet_v2(weights=None, num_classes=1000).train().to(device)
        opt = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.9)
        loss_fn = torch.nn.CrossEntropyLoss()
        data = torch.randn(args.batch_size, 3, args.image_size, args.image_size, device=device)
        target = torch.randint(0, 1000, (args.batch_size,), device=device)
        unit = "samples/s"

        def step() -> None:
            with torch.cuda.stream(stream):
                opt.zero_grad(set_to_none=True)
                out = model(data)
                loss = loss_fn(out, target)
                loss.backward()
                opt.step()

    else:
        raise RuntimeError(f"unknown workload: {args.workload}")

    for _ in range(args.warmup):
        step()
        stream.synchronize()

    while True:
        start = time.time()
        for _ in range(args.run_cnt):
            step()
        stream.synchronize()
        elapsed = time.time() - start
        print(f"thpt: {args.batch_size * args.run_cnt / elapsed:.2f} {unit}", flush=True)


def main() -> int:
    args = parse_args()
    if args.worker:
        return worker_loop(args)
    if args.lp_count < 0 or args.hp_count < 0:
        raise SystemExit("--lp-count and --hp-count must be non-negative")
    if args.lp_count == 0 and args.hp_count == 0:
        raise SystemExit("nothing to run")
    if args.mode == "xsched" and not OUTPUT_LIB.exists():
        raise SystemExit(f"missing output lib directory: {OUTPUT_LIB}")

    result_dir = make_result_dir(args.result_dir)
    csv_rows: list[dict[str, object]] = []
    rows_lock = threading.Lock()
    specs: list[ProcSpec] = []
    threads: list[threading.Thread] = []
    xserver_proc: subprocess.Popen[str] | None = None
    t0 = time.time()

    config = vars(args).copy()
    config["result_dir"] = str(result_dir)
    config["standard_workloads"] = {
        "cnn": "ResNet50 inference",
        "transformer": "synthetic TransformerEncoder inference",
        "train": "MobileNetV2 batch training",
    }
    (result_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    try:
        xserver_proc = start_xserver(args, result_dir)

        for i in range(args.lp_count):
            spec, thread = launch_role(args, "lp", args.lp_workload, 0, i,
                                       result_dir, t0, csv_rows, rows_lock)
            specs.append(spec)
            threads.append(thread)
            time.sleep(0.5)

        print(f"waiting {args.hp_delay:.1f}s before starting HP", flush=True)
        time.sleep(args.hp_delay)

        for i in range(args.hp_count):
            spec, thread = launch_role(args, "hp", args.hp_workload, 1, i,
                                       result_dir, t0, csv_rows, rows_lock)
            specs.append(spec)
            threads.append(thread)
            time.sleep(0.5)

        print(f"collecting {args.duration_after_hp:.1f}s after HP start", flush=True)
        time.sleep(args.duration_after_hp)
    finally:
        for spec in specs:
            terminate_proc(spec.proc)
        for thread in threads:
            thread.join(timeout=2.0)
        for spec in specs:
            spec.log_file.close()
        if xserver_proc is not None:
            terminate_proc(xserver_proc)

    with rows_lock:
        rows = list(csv_rows)
    write_csv(result_dir / "throughput.csv", rows)
    summary = summarize(specs)
    (result_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"\nresults: {result_dir}")
    print(f"csv:     {result_dir / 'throughput.csv'}")
    print(f"summary: {result_dir / 'summary.json'}")
    for item in summary:
        print(
            f"{item['role']}[{item['index']}] workload={item['workload']} "
            f"prio={item['priority']} samples={item['samples']} "
            f"first_thpt_delay_s={item['first_thpt_delay_s']} "
            f"hp_wait_block_time_s={item['hp_wait_block_time_s']} "
            f"avg={item['avg_throughput']} {item['unit']} "
            f"last={item['last_throughput']} peak={item['peak_throughput']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
