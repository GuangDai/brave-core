#!/usr/bin/env python3
"""Export generated Ninja metadata without the Chromium source or objects."""

import argparse
from pathlib import Path
import subprocess
import tarfile


def export(build, destination):
    build = build.resolve()
    if not (build / "build.ninja").is_file():
        raise RuntimeError("The generated browser graph is missing")
    paths = sorted(build.rglob("*.ninja"))
    if not paths or any(path.is_symlink() or not path.is_file() for path in paths):
        raise RuntimeError("The graph contains unsupported Ninja entries")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        compressor = subprocess.Popen(["zstd", "-1", "-T2", "-q", "-c"],
                                      stdin=subprocess.PIPE, stdout=output)
        with tarfile.open(fileobj=compressor.stdin, mode="w|") as archive:
            for path in paths:
                archive.add(path, arcname=path.relative_to(build), recursive=False)
        compressor.stdin.close()
        if compressor.wait() != 0:
            raise RuntimeError("Could not compress the Ninja graph")
    print(f"Exported {len(paths)} Ninja files: {destination.stat().st_size} bytes", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.build, args.output)


if __name__ == "__main__":
    main()
