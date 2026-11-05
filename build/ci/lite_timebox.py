#!/usr/bin/env python3
"""Stop a CI build in time to save a checkpoint."""

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=90)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def directory_size(directory):
    if not directory or not directory.exists():
        return 0
    size = 0
    for path in directory.rglob("*"):
        try:
            if path.is_file():
                size += path.stat().st_size
        except FileNotFoundError:
            # ccache may rename a temporary entry while it is being counted.
            continue
    return size


def run_build(command, workspace, deadline, reserve_bytes, cache_dir=None,
              cache_limit_bytes=0):
    if time.time() >= deadline:
        return "checkpoint", "time", 0
    if shutil.disk_usage(workspace).free < reserve_bytes:
        return "checkpoint", "disk", 0
    process = subprocess.Popen(command, start_new_session=True)
    next_cache_check = time.monotonic()
    while True:
        try:
            result = process.wait(timeout=max(0.1, min(10, deadline - time.time())))
            return ("complete", "", 0) if result == 0 else ("failed", "", result)
        except subprocess.TimeoutExpired:
            pass
        if time.time() >= deadline:
            stop_group(process)
            return "checkpoint", "time", 0
        if shutil.disk_usage(workspace).free < reserve_bytes:
            stop_group(process)
            return "checkpoint", "disk", 0
        if cache_limit_bytes and time.monotonic() >= next_cache_check:
            next_cache_check = time.monotonic() + 60
            if directory_size(cache_dir) >= cache_limit_bytes:
                stop_group(process)
                return "checkpoint", "cache", 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--started", type=int, required=True)
    parser.add_argument("--budget-minutes", type=int, default=265)
    parser.add_argument("--reserve-gib", type=int, default=24)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--cache-limit-gib", type=int, default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if (not command or args.budget_minutes <= 0 or args.reserve_gib < 0
            or args.cache_limit_gib < 0
            or (args.cache_limit_gib and not args.cache_dir)):
        parser.error("A command and valid budget are required")
    outcome, reason, status = run_build(
        command, args.workspace, args.started + args.budget_minutes * 60,
        args.reserve_gib * 1024 ** 3, args.cache_dir,
        args.cache_limit_gib * 1024 ** 3,
    )
    print(f"Build outcome: {outcome}; reason: {reason or 'none'}", flush=True)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"outcome={outcome}\nreason={reason}\n")
    return status if status > 0 else (1 if status < 0 else 0)


if __name__ == "__main__":
    sys.exit(main())
