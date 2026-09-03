#!/usr/bin/env python3
"""Profile the reproduction sequentially with Rust 1.98 on macOS or Windows."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILES = ROOT / "profiles"
TOOLCHAIN = "1.98.0"
PACKAGES = [
    "monolithic",
    "flattened",
    "model_only",
    "boundary_model",
    "direct_consumer",
    "boundary_consumer",
]


def run(command, **kwargs):
    print("+", " ".join(map(str, command)), flush=True)
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


run([sys.executable, ROOT / "generate.py"])
PROFILES.mkdir(exist_ok=True)
env = os.environ.copy()
env["RUSTC_BOOTSTRAP"] = "1"
run(["cargo", f"+{TOOLCHAIN}", "build", "--release", "-p", "primer"], env=env)

results = []
for package in PACKAGES:
    destination = PROFILES / package
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir()
    log_path = destination / "rustc.log"
    run(["cargo", f"+{TOOLCHAIN}", "clean", "-p", package], env=env)
    if package == "direct_consumer":
        run(["cargo", f"+{TOOLCHAIN}", "build", "--release", "-p", "model_only"], env=env)
    elif package == "boundary_consumer":
        # Keep the owner's expensive monomorphization outside the consumer's
        # measurement. The point of this case is what each downstream crate pays.
        run(["cargo", f"+{TOOLCHAIN}", "build", "--release", "-p", "boundary_model"], env=env)
    command = [
        "cargo", f"+{TOOLCHAIN}", "rustc", "--release", "-p", package, "--",
        f"-Zself-profile={destination}", "-Ztime-passes", "-Zllvm-time-trace",
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    log_path.write_text(completed.stdout)
    print(completed.stdout, end="")
    if completed.returncode:
        raise SystemExit(completed.returncode)
    phases = {
        match.group("name"): float(match.group("seconds"))
        for match in re.finditer(r"^time:\s+(?P<seconds>[0-9.]+);.*\t(?P<name>\S+)$", completed.stdout, re.MULTILINE)
    }
    trace = max(
        (ROOT / "target" / "release" / "deps").glob(f"{package}-*.llvm_timings.json"),
        key=lambda path: path.stat().st_mtime,
    )
    shutil.copy2(trace, destination / "llvm_timings.json")
    events = json.loads(trace.read_text())["traceEvents"]
    llvm_passes = {}
    for name in ("LICMPass", "InstCombinePass", "SLPVectorizerPass"):
        matching = [event for event in events if event.get("ph") == "X" and event.get("name") == name]
        llvm_passes[name] = {
            "seconds": sum(event["dur"] for event in matching) / 1_000_000,
            "invocations": len(matching),
        }
    result = {
        "package": package,
        "cargo_elapsed_seconds": elapsed,
        "rustc_total_seconds": phases.get("total"),
        "phases": phases,
        "llvm_passes": llvm_passes,
    }
    (destination / "summary.json").write_text(json.dumps(result, indent=2))
    results.append(result)
    print(json.dumps(result), flush=True)

(PROFILES / "summary.json").write_text(json.dumps(results, indent=2))
run(["cargo", f"+{TOOLCHAIN}", "run", "--release", "-p", "runtime_bench"], env=env)
