#!/usr/bin/env python3
"""Prototype output-only checkpoints against a verified source baseline."""

import json
import os
from pathlib import Path
import shutil
import stat

import lite_checkpoint


OUTPUT = Path("src/out")
EXCLUDED = {".git", ".lite-tools"}


def source_inventory(workspace):
    workspace = workspace.resolve()
    result = {}
    for parent, dirs, files in os.walk(workspace, followlinks=False):
        parent = Path(parent)
        for name in list(dirs):
            path = parent / name
            relative = path.relative_to(workspace)
            if name in EXCLUDED or relative == OUTPUT:
                dirs.remove(name)
            elif path.is_symlink():
                result[relative.as_posix()] = {"kind": "symlink", "target": os.readlink(path)}
                dirs.remove(name)
        for name in files:
            if name in EXCLUDED:
                continue
            path = parent / name
            relative = path.relative_to(workspace).as_posix()
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                result[relative] = {"kind": "symlink", "target": os.readlink(path)}
            elif stat.S_ISREG(metadata.st_mode):
                result[relative] = {"kind": "file", "size": metadata.st_size,
                                    "sha256": lite_checkpoint.digest(path),
                                    "mtime_ns": metadata.st_mtime_ns,
                                    "mode": stat.S_IMODE(metadata.st_mode)}
            else:
                raise RuntimeError(f"Unsupported source file type: {relative}")
    return dict(sorted(result.items()))


def same_content(left, right):
    if left.get("kind") != right.get("kind"):
        return False
    if left.get("kind") == "symlink":
        return left.get("target") == right.get("target")
    return all(left.get(key) == right.get(key) for key in ("size", "sha256", "mode"))


def validate_relative(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Invalid checkpoint path: {name!r}")
    return path


def link_tree(source, destination):
    metadata = source.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(os.readlink(source))
    elif stat.S_ISREG(metadata.st_mode):
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, destination, follow_symlinks=False)
    elif stat.S_ISDIR(metadata.st_mode):
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir()):
            link_tree(child, destination / child.name)
        os.chmod(destination, stat.S_IMODE(metadata.st_mode))
        os.utime(destination, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    else:
        raise RuntimeError(f"Unsupported output type: {source}")


def capture_baseline(workspace, destination):
    if destination.exists():
        raise RuntimeError("Baseline destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = source_inventory(workspace)
    destination.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"Recorded {len(data)} source files and symlinks", flush=True)


def save(workspace, baseline_path, staging, checkpoint, build_identity,
         volume_bytes=lite_checkpoint.DEFAULT_VOLUME_BYTES):
    workspace = workspace.resolve()
    if staging.resolve().is_relative_to(workspace) or checkpoint.resolve().is_relative_to(workspace):
        raise ValueError("Checkpoint staging and output must be outside the source workspace")
    baseline = json.loads(baseline_path.read_text())
    current = source_inventory(workspace)
    missing = set(baseline) - set(current)
    if missing:
        raise RuntimeError(f"Source files were removed: {sorted(missing)[:5]}")
    changed = sorted(name for name, value in current.items() if baseline.get(name) != value)
    changed_symlinks = [name for name in changed if name in baseline
                        and current[name].get("kind") == "symlink"
                        and baseline[name] != current[name]]
    if changed_symlinks:
        raise RuntimeError(f"Source symlinks changed: {changed_symlinks[:5]}")
    output = workspace / OUTPUT
    if not output.is_dir() or output.is_symlink():
        raise RuntimeError("The build output directory does not exist")
    staging.mkdir(parents=True, exist_ok=False)
    tree = staging / "tree"
    for name in changed:
        relative = validate_relative(name)
        link_tree(workspace / relative, tree / relative)
    link_tree(output, tree / OUTPUT)
    (staging / "baseline.json").write_text(json.dumps(baseline, separators=(",", ":")) + "\n")
    (staging / "delta.json").write_text(json.dumps(changed, separators=(",", ":")) + "\n")
    lite_checkpoint.save(staging, checkpoint, build_identity, volume_bytes)
    print(f"Saved build output and {len(changed)} changed source paths", flush=True)


def restore(workspace, checkpoint, staging, build_identity):
    workspace = workspace.resolve()
    if staging.resolve().is_relative_to(workspace) or checkpoint.resolve().is_relative_to(workspace):
        raise ValueError("Checkpoint staging and input must be outside the source workspace")
    if (workspace / OUTPUT).exists():
        raise RuntimeError("Restore requires a fresh source tree without build output")
    lite_checkpoint.restore(staging, checkpoint, build_identity)
    baseline = json.loads((staging / "baseline.json").read_text())
    changed = json.loads((staging / "delta.json").read_text())
    if not isinstance(baseline, dict) or not isinstance(changed, list):
        raise RuntimeError("Invalid baseline or source changes")
    changed_set = {validate_relative(name).as_posix() for name in changed}
    current = source_inventory(workspace)
    missing = set(baseline) - set(current)
    extras = set(current) - set(baseline) - changed_set
    differences = [name for name, old in baseline.items()
                   if name in current and name not in changed_set
                   and not same_content(old, current[name])]
    if missing or extras or differences:
        raise RuntimeError("Fresh source differs from baseline: "
                           f"missing={sorted(missing)[:3]}, extra={sorted(extras)[:3]}, "
                           f"changed={sorted(differences)[:3]}")

    for name, old in baseline.items():
        if name not in changed_set and old.get("kind") == "file":
            path = workspace / validate_relative(name)
            metadata = path.stat()
            os.utime(path, ns=(metadata.st_atime_ns, old["mtime_ns"]))

    tree = staging / "tree"
    for name in changed:
        relative = validate_relative(name)
        source, destination = tree / relative, workspace / relative
        if source.is_symlink():
            if destination.exists() or destination.is_symlink():
                raise RuntimeError(f"Cannot replace existing source symlink: {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(os.readlink(source))
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink():
                raise RuntimeError(f"Cannot replace existing source symlink: {name}")
            shutil.copyfile(source, destination)
            shutil.copystat(source, destination)
        else:
            raise RuntimeError(f"Missing changed source path: {name}")
    link_tree(tree / OUTPUT, workspace / OUTPUT)
    print(f"Restored build output and {len(changed)} changed source paths", flush=True)
