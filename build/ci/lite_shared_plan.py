#!/usr/bin/env python3
"""Plan shared prerequisites and five object groups without compiling."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

import lite_partition_graph


COMPILE = re.compile(rb"(?:^|\s)-c(?:\s|$)")
OUTPUT = re.compile(rb"(?:^|\s)-o\s+([^\s]+\.o)(?:\s|$)")


def commands(ninja, build, manifest, target):
    proc = subprocess.Popen([str(ninja), "-C", str(build), "-f", manifest,
                             "-t", "commands", target], stdout=subprocess.PIPE)
    all_commands, compiles, outputs = set(), set(), {}
    with proc.stdout:
        for line in proc.stdout:
            digest = hashlib.sha256(line).digest()
            all_commands.add(digest)
            if not COMPILE.search(line):
                continue
            compiles.add(digest)
            match = OUTPUT.search(line)
            if not match:
                continue
            try:
                output = match.group(1).decode("utf-8")
            except UnicodeDecodeError:
                continue
            if (".." in output.split("/") or
                    any(character in output for character in "\n\r\t\0|#\\\"'")):
                continue
            if output in outputs and outputs[output] != digest:
                raise RuntimeError(f"Different commands produce {output}")
            outputs[output] = digest
    if proc.wait() != 0:
        raise RuntimeError(f"Could not inspect {target}")
    return all_commands, compiles, outputs


def statistics(groups):
    masks = {}
    for index, group in enumerate(groups):
        for digest in group:
            masks[digest] = masks.get(digest, 0) | (1 << index)
    frequencies = Counter(mask.bit_count() for mask in masks.values())
    return {"unique": len(masks),
            "executions": sum(count * number for count, number in frequencies.items()),
            "repeated": sum((count - 1) * number for count, number in frequencies.items())}


def write_shared(build, shared):
    if not shared:
        raise RuntimeError("No shared object prerequisites were found")
    lines = ["include build.ninja\nbuild brave_lite_shared: phony $\n"]
    for index, name in enumerate(shared):
        escaped = name.replace("$", "$$").replace(" ", "$ ").replace(":", "$:")
        continuation = " $" if index + 1 < len(shared) else ""
        lines.append(f"  {escaped}{continuation}\n")
    (build / "brave_lite_shared.ninja").write_text("".join(lines))


def plan(ninja, build):
    ninja, build = ninja.resolve(), build.resolve()
    proc = subprocess.Popen([str(ninja), "-C", str(build), "-t", "graph", "brave"],
                            stdout=subprocess.PIPE, text=True)
    with proc.stdout:
        objects = lite_partition_graph.graph_objects(proc.stdout)
    if proc.wait() != 0:
        raise RuntimeError("Could not read the browser build graph")
    groups = lite_partition_graph.partition(objects)["group"]
    lite_partition_graph.write_groups(build, {"group": groups})

    command_sets, compile_sets, masks, output_keys = [], [], {}, {}
    for index in range(5):
        all_commands, compiles, outputs = commands(
            ninja, build, "brave_lite_graph.ninja", f"brave_lite_group_{index + 1}")
        command_sets.append(all_commands)
        compile_sets.append(compiles)
        for name, digest in outputs.items():
            if name in output_keys and output_keys[name] != digest:
                raise RuntimeError(f"Inconsistent commands for {name}")
            output_keys[name] = digest
            masks[name] = masks.get(name, 0) | (1 << index)

    shared = sorted(name for name, mask in masks.items() if mask.bit_count() >= 2)
    write_shared(build, shared)
    bootstrap, bootstrap_compiles, _ = commands(
        ninja, build, "brave_lite_shared.ninja", "brave_lite_shared")
    return {"object_count": len(objects),
            "object_list_sha256": hashlib.sha256("\n".join(objects).encode()).hexdigest(),
            "objects_per_group": [len(group) for group in groups],
            "shared_object_count": len(shared),
            "bootstrap": {"commands": len(bootstrap), "compiler_commands": len(bootstrap_compiles)},
            "groups_before": {"commands": statistics(command_sets),
                              "compiler_commands": statistics(compile_sets)},
            "groups_after": {"commands": statistics([group - bootstrap for group in command_sets]),
                             "compiler_commands": statistics([group - bootstrap for group in compile_sets])}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ninja", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = plan(args.ninja, args.build)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
