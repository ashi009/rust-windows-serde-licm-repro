#!/usr/bin/env python3
"""Cross-profile the minimal rlib for the Windows MSVC target."""
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
TARGET = "x86_64-pc-windows-msvc"


def run(command, **kwargs):
    print("+", " ".join(map(str, command)), flush=True)
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


run([sys.executable, ROOT / "generate.py"])
installed = subprocess.run(
    ["rustup", "target", "list", "--toolchain", TOOLCHAIN, "--installed"],
    check=True,
    text=True,
    stdout=subprocess.PIPE,
).stdout.splitlines()
if TARGET not in installed:
    raise SystemExit(
        f"missing target {TARGET}; run: rustup target add {TARGET} --toolchain {TOOLCHAIN}"
    )

PROFILES.mkdir(exist_ok=True)
env = os.environ.copy()
env["RUSTC_BOOTSTRAP"] = "1"
run(["cargo", f"+{TOOLCHAIN}", "build", "--release", "--target", TARGET, "-p", "primer"], env=env)

results = []
cases = [
    ("monolithic", "unwind"),
    ("monolithic", "abort"),
    ("flattened", "unwind"),
]
for package, strategy in cases:
    label = f"{package}-windows-msvc-{strategy}"
    destination = PROFILES / label
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir()
    run(["cargo", f"+{TOOLCHAIN}", "clean", "--target", TARGET, "-p", package], env=env)
    command = [
        "cargo", f"+{TOOLCHAIN}", "rustc", "--release", "--target", TARGET,
        "-p", package, "--", f"-Cpanic={strategy}",
        f"-Zself-profile={destination}", "-Ztime-passes", "-Zllvm-time-trace",
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    elapsed = time.perf_counter() - started
    (destination / "rustc.log").write_text(completed.stdout)
    print(completed.stdout, end="")
    if completed.returncode:
        raise SystemExit(completed.returncode)

    phases = {
        match.group("name"): float(match.group("seconds"))
        for match in re.finditer(
            r"^time:\s+(?P<seconds>[0-9.]+);.*\t(?P<name>\S+)$",
            completed.stdout,
            re.MULTILINE,
        )
    }
    trace = max(
        (ROOT / "target" / TARGET / "release" / "deps").glob(f"{package}-*.llvm_timings.json"),
        key=lambda path: path.stat().st_mtime,
    )
    shutil.copy2(trace, destination / "llvm_timings.json")
    events = json.loads(trace.read_text())["traceEvents"]
    licm = [event for event in events if event.get("ph") == "X" and event.get("name") == "LICMPass"]
    visitor_licm = [event for event in licm if "visit_map" in event.get("args", {}).get("detail", "")]
    result = {
        "package": package,
        "panic": strategy,
        "cargo_elapsed_seconds": elapsed,
        "rustc_total_seconds": phases.get("total"),
        "licm_seconds": sum(event["dur"] for event in licm) / 1_000_000,
        "licm_invocations": len(licm),
        "visitor_licm_seconds": sum(event["dur"] for event in visitor_licm) / 1_000_000,
        "visitor_licm_invocations": len(visitor_licm),
    }
    (destination / "summary.json").write_text(json.dumps(result, indent=2))
    results.append(result)
    print(json.dumps(result), flush=True)

(PROFILES / "windows-msvc-summary.json").write_text(json.dumps(results, indent=2))
