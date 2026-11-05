#!/usr/bin/env python3
"""Save and restore an integrity-checked, multi-volume CI build checkpoint."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


MAX_VOLUMES = 8
DEFAULT_VOLUME_BYTES = 4 * 1024 * 1024 * 1024
MANIFEST = "manifest.json"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def identity(repository, commit, workspace, require_runner=True):
    if platform.system() != "Darwin":
        raise RuntimeError("The build checkpoint requires a macOS runner")
    if not repository or not commit:
        raise RuntimeError("Repository and commit must be set")
    image_version = os.environ.get("ImageVersion", "")
    if require_runner and not image_version:
        raise RuntimeError("Runner image version is unavailable")
    return {
        "repository": repository,
        "commit": commit,
        "workspace": str(workspace.resolve()),
        "architecture": platform.machine(),
        "image_os": os.environ.get("ImageOS", ""),
        "image_version": image_version,
        "macos_version": subprocess.check_output(
            ["sw_vers", "-productVersion"], text=True
        ).strip(),
        "xcode_version": subprocess.check_output(
            ["xcodebuild", "-version"], text=True
        ).strip(),
        "sdk_version": subprocess.check_output(
            ["xcrun", "--sdk", "macosx", "--show-sdk-version"], text=True
        ).strip(),
    }


def compatible_identity(saved, current):
    required = ("repository", "commit", "workspace", "architecture", "image_os",
                "xcode_version", "sdk_version")
    if not isinstance(saved, dict) or not all(
        key in saved and saved[key] == current.get(key) for key in required
    ):
        return False
    old_os = saved.get("macos_version", "").split(".")[0]
    new_os = current.get("macos_version", "").split(".")[0]
    return bool(old_os) and old_os == new_os


def check_pipeline(processes):
    results = [proc.wait() for proc in reversed(processes)]
    if any(results):
        raise RuntimeError(f"Checkpoint pipeline failed: {list(reversed(results))}")


def save(workspace, destination, build_identity, volume_bytes=DEFAULT_VOLUME_BYTES):
    workspace, destination = workspace.resolve(), destination.resolve()
    if not workspace.is_dir() or destination.is_relative_to(workspace):
        raise ValueError("Checkpoint destination must be outside the workspace")
    if volume_bytes < 1:
        raise ValueError("Volume size must be positive")
    destination.mkdir(parents=True, exist_ok=False)

    env = {**os.environ, "COPYFILE_DISABLE": "1"}
    tar = subprocess.Popen(
        ["tar", "-C", str(workspace), "--exclude=./.lite-tools", "-cf", "-", "."],
        stdout=subprocess.PIPE,
        env=env,
    )
    compressor = subprocess.Popen(
        ["zstd", "-T2", "-1", "-q", "-c"],
        stdin=tar.stdout,
        stdout=subprocess.PIPE,
    )
    tar.stdout.close()
    splitter = subprocess.Popen(
        ["split", "-a", "2", "-b", str(volume_bytes), "-", str(destination / "part-")],
        stdin=compressor.stdout,
    )
    compressor.stdout.close()
    check_pipeline([tar, compressor, splitter])

    volumes = sorted(destination.glob("part-??"))
    if not volumes or len(volumes) > MAX_VOLUMES:
        raise RuntimeError(f"Checkpoint has {len(volumes)} volumes; maximum is {MAX_VOLUMES}")
    manifest = {
        "version": 1,
        "identity": build_identity,
        "volumes": [
            {"name": p.name, "size": p.stat().st_size, "sha256": digest(p)}
            for p in volumes
        ],
    }
    (destination / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved {len(volumes)} verified checkpoint volume(s)", flush=True)


def restore(workspace, source, build_identity):
    workspace, source = workspace.resolve(), source.resolve()
    if source.is_relative_to(workspace):
        raise ValueError("Checkpoint source must be outside the workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    unexpected = [p.name for p in workspace.iterdir() if p.name != ".lite-tools"]
    if unexpected:
        raise RuntimeError(f"Restore workspace is not empty: {unexpected}")
    manifest = json.loads((source / MANIFEST).read_text())
    saved_identity = manifest.get("identity")
    if manifest.get("version") != 1 or not compatible_identity(saved_identity, build_identity):
        raise RuntimeError("Checkpoint repository, commit or toolchain differs")
    if saved_identity != build_identity:
        print("Runner image or macOS minor version changed; Xcode and SDK match", flush=True)
    volumes = manifest.get("volumes")
    if not isinstance(volumes, list) or not 1 <= len(volumes) <= MAX_VOLUMES:
        raise RuntimeError("Invalid checkpoint volume list")
    paths = []
    for index, volume in enumerate(volumes):
        expected_name = f"part-a{chr(ord('a') + index)}"
        if not isinstance(volume, dict) or volume.get("name") != expected_name:
            raise RuntimeError("Checkpoint volumes are missing or out of order")
        path = source / expected_name
        if (not path.is_file() or path.stat().st_size != volume.get("size")
                or digest(path) != volume.get("sha256")):
            raise RuntimeError(f"Checkpoint volume failed verification: {expected_name}")
        paths.append(str(path))
    actual = {p.name for p in source.glob("part-*")}
    if actual != {Path(p).name for p in paths}:
        raise RuntimeError("Checkpoint has unexpected volumes")

    cat = subprocess.Popen(["cat", *paths], stdout=subprocess.PIPE)
    decompressor = subprocess.Popen(
        ["zstd", "-d", "-q", "-c"], stdin=cat.stdout, stdout=subprocess.PIPE
    )
    cat.stdout.close()
    tar = subprocess.Popen(
        ["tar", "-C", str(workspace), "-xf", "-"], stdin=decompressor.stdout
    )
    decompressor.stdout.close()
    check_pipeline([cat, decompressor, tar])
    print(f"Restored {len(paths)} verified checkpoint volume(s)", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["save", "restore"])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    build_identity = identity(args.repository, args.commit, args.workspace)
    if args.action == "save":
        save(args.workspace, args.checkpoint, build_identity)
    else:
        restore(args.workspace, args.checkpoint, build_identity)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Checkpoint error: {error}", file=sys.stderr)
        sys.exit(1)
