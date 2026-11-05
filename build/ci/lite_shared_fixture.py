#!/usr/bin/env python3
"""Create and verify a tiny shared-prerequisite handoff fixture."""

import argparse
from pathlib import Path


def create(root, build_name="Static"):
    config = root / "build/config/siso"
    build = root / "out" / build_name
    config.mkdir(parents=True)
    build.mkdir(parents=True)
    (root / ".gn").write_text("")
    (config / "main.star").write_text('''\
load("@builtin//encoding.star", "json")
load("@builtin//struct.star", "module")
def init(ctx):
    return module("config", step_config=json.encode({"rules": [], "platforms": {}, "input_deps": {}}),
                  filegroups={}, handlers={})
''')
    (root / "fakecc.py").write_text('''\
from pathlib import Path
import sys
out = sys.argv[sys.argv.index('-o') + 1]
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text(out)
with open('compiled.log', 'a') as log:
    log.write(out + '\\n')
''')
    (root / "shared.c").write_text("shared")
    for index in range(5):
        (root / f"leaf{index}.c").write_text(f"leaf {index}")
    graph = ['rule cc\n  command = python3 ../../fakecc.py -c $in -o $out\n',
             'build obj/shared.o: cc ../../shared.c\n']
    for index in range(5):
        graph.append(f'build obj/leaf{index}.o: cc ../../leaf{index}.c | obj/shared.o\n')
    graph.append('build brave: phony ' + ' '.join(
        f'obj/leaf{index}.o' for index in range(5)) + '\n')
    (build / "build.ninja").write_text(''.join(graph))


def verify(root, expect_leaf, build_name="Static"):
    compiled = (root / "out" / build_name / "compiled.log").read_text().splitlines()
    if compiled.count("obj/shared.o") != 1:
        raise RuntimeError(f"Shared prerequisite was rebuilt: {compiled}")
    leaves = [line for line in compiled if line.startswith("obj/leaf")]
    if len(leaves) != int(expect_leaf):
        raise RuntimeError(f"Unexpected group outputs: {compiled}")
    print("Verified shared prerequisite and group outputs:", compiled)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "bootstrap", "group"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--build-name", default="Static")
    args = parser.parse_args()
    if args.build_name not in ("Static", "Static_arm64"):
        parser.error("Invalid fixture build name")
    if args.action == "create":
        create(args.root, args.build_name)
    else:
        verify(args.root, args.action == "group", args.build_name)


if __name__ == "__main__":
    main()
