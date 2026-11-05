#!/usr/bin/env python3
"""Compare disjoint object partitions without executing build commands."""

import argparse
from collections import Counter, defaultdict
import hashlib
import heapq
import json
from pathlib import Path
import re
import subprocess


SHARDS = 5
OBJECT_PATH = re.compile(r"obj/[A-Za-z0-9_+./@-]+\.o\Z")
NODE = re.compile(r'^"0x[0-9a-fA-F]+" \[label="((?:\\.|[^"\\])*)"\]$')
COMPILE = re.compile(r"(?:^|\s)-c(?:\s|$)")


def graph_objects(lines):
    objects = set()
    for line in lines:
        match = NODE.match(line.strip())
        if not match:
            continue
        name = json.loads('"' + match.group(1) + '"')
        if name.startswith("obj/") and name.endswith(".o"):
            if not OBJECT_PATH.fullmatch(name) or ".." in name.split("/"):
                raise ValueError(f"Unsupported object name: {name!r}")
            objects.add(name)
    if not objects:
        raise RuntimeError("The browser graph contains no object files")
    return sorted(objects)


def partition(objects):
    if len(objects) < SHARDS:
        raise ValueError("Not enough objects to split")
    round_robin = [[] for _ in range(SHARDS)]
    for index, name in enumerate(objects):
        round_robin[index % SHARDS].append(name)

    dirs = defaultdict(list)
    for name in objects:
        dirs[name.rsplit("/", 1)[0]].append(name)
    chunks = [names[i:i + 128] for names in dirs.values()
              for i in range(0, len(names), 128)]
    chunks.sort(key=lambda names: (-len(names), names[0]))
    grouped = [[] for _ in range(SHARDS)]
    available = [(0, index) for index in range(SHARDS)]
    heapq.heapify(available)
    for chunk in chunks:
        count, index = heapq.heappop(available)
        grouped[index].extend(chunk)
        heapq.heappush(available, (count + len(chunk), index))
    return {"round": round_robin, "group": grouped}


def write_groups(build, groups):
    text = []
    for algorithm, shards in groups.items():
        for index, objects in enumerate(shards, 1):
            target = f"brave_lite_{algorithm}_{index}"
            text.append(f"build {target}: phony $\n")
            for position, name in enumerate(objects):
                continuation = " $" if position + 1 < len(objects) else ""
                text.append(f"  {name}{continuation}\n")
    (build / "brave_lite_partitions.ninja").write_text("".join(text))
    (build / "brave_lite_graph.ninja").write_text(
        "include build.ninja\ninclude brave_lite_partitions.ninja\n"
    )


def measure(ninja, build, algorithm):
    commands = {}
    compiles = {}
    counts = []
    for index in range(SHARDS):
        proc = subprocess.Popen(
            [str(ninja), "-C", str(build), "-f", "brave_lite_graph.ninja",
             "-t", "commands", f"brave_lite_{algorithm}_{index + 1}"],
            stdout=subprocess.PIPE, text=True,
        )
        count = 0
        for line in proc.stdout:
            key = hashlib.sha256(line.encode()).digest()[:16]
            commands[key] = commands.get(key, 0) | (1 << index)
            if COMPILE.search(line):
                compiles[key] = compiles.get(key, 0) | (1 << index)
            count += 1
        if proc.wait() != 0:
            raise RuntimeError(f"Could not inspect {algorithm} shard {index + 1}")
        counts.append(count)

    def stats(items):
        frequencies = Counter(mask.bit_count() for mask in items.values())
        return {"unique": len(items),
                "executions": sum(count * frequency for count, frequency in frequencies.items()),
                "repeated": sum((count - 1) * frequency for count, frequency in frequencies.items())}

    return {"commands_per_shard": counts, "all_commands": stats(commands),
            "compiler_commands": stats(compiles)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ninja", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    ninja, build = args.ninja.resolve(), args.build.resolve()
    proc = subprocess.Popen([str(ninja), "-C", str(build), "-t", "graph", "brave"],
                            stdout=subprocess.PIPE, text=True)
    objects = graph_objects(proc.stdout)
    if proc.wait() != 0:
        raise RuntimeError("Could not read the browser build graph")
    groups = partition(objects)
    write_groups(build, groups)
    report = {"object_count": len(objects),
              "object_list_sha256": hashlib.sha256("\n".join(objects).encode()).hexdigest(),
              "algorithms": {}}
    for algorithm, shards in groups.items():
        report["algorithms"][algorithm] = {
            "objects_per_shard": [len(shard) for shard in shards],
            **measure(ninja, build, algorithm),
        }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
