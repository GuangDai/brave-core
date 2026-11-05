#!/usr/bin/env python3
"""Verify downloaded CI caches and print a portable ccache configuration."""

import argparse
import json
import platform
from pathlib import Path
import re
import shlex
import sys

from lite_shard_cache import TARGETS, entries


SHARD = re.compile(r"brave-lite-shard-([1-5])(?:-part-([1-4]))?-a([0-9]+)\Z")
STAGE = re.compile(r"brave-lite-stage-([1-8])-shard-([1-5])-part-([1-4])-a([0-9]+)\Z")
RUN = re.compile(r"run-([0-9]+)\Z")
OUTCOMES = {"complete", "checkpoint", "failed"}


def artifact_info(name):
    if match := STAGE.fullmatch(name):
        stage, shard, part, attempt = match.groups()
        if int(attempt) < 1:
            raise ValueError(f"Invalid cache attempt: {name}")
        return {"stage": int(stage), "shard": shard, "part": int(part), "attempt": int(attempt)}
    if match := SHARD.fullmatch(name):
        shard, part, attempt = match.groups()
        if int(attempt) < 1:
            raise ValueError(f"Invalid cache attempt: {name}")
        return {"stage": 0, "shard": shard, "part": int(part) if part else None,
                "attempt": int(attempt)}
    return None


def discover(roots):
    """Discover only artifact directories and immediate run-ID children."""
    found = []
    seen = set()
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"Root must be a non-symlink directory: {root}")
        candidates = []
        if artifact_info(root.name):
            candidates.append(root)
        else:
            for child in sorted(root.iterdir()):
                if artifact_info(child.name):
                    candidates.append(child)
                elif RUN.fullmatch(child.name):
                    if child.is_symlink() or not child.is_dir():
                        raise ValueError(f"Run must be a non-symlink directory: {child}")
                    candidates.extend(path for path in child.iterdir() if artifact_info(path.name))
        def priority(path):
            item = artifact_info(path.name)
            run = RUN.fullmatch(path.parent.name)
            return (int(run.group(1)) if run else 0, item["attempt"], item["stage"],
                    int(item["shard"]), item["part"] or 0, path.name)
        for path in sorted(candidates, key=priority, reverse=True):
            if path.is_symlink() or not path.is_dir():
                raise ValueError(f"Artifact must be a non-symlink directory: {path}")
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
    if not found:
        raise ValueError("No supported compiler cache artifacts were found")
    return found


def verify_artifact(path, repository):
    """Check the whole artifact before returning its cache directory."""
    info = artifact_info(path.name)
    if not info or path.is_symlink() or not path.is_dir():
        raise ValueError(f"Invalid cache artifact: {path}")
    manifest_path = path / "manifest.json"
    cache = path / "cache"
    if manifest_path.is_symlink() or not manifest_path.is_file() or cache.is_symlink():
        raise ValueError(f"Invalid manifest or cache path: {path}")
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError(f"Invalid cache manifest: {path}")
    identity = manifest.get("identity")
    if (type(manifest.get("version")) is not int or manifest.get("version") != 1 or not isinstance(identity, dict)
            or identity.get("repository") != repository or identity.get("architecture") != "arm64"
            or manifest.get("shard") != info["shard"]
            or manifest.get("target") != TARGETS[info["shard"]]
            or not isinstance(manifest.get("outcome"), str)
            or manifest.get("outcome") not in OUTCOMES
            or (info["part"] is not None and (type(manifest.get("part")) is not int
                                                or manifest.get("part") != info["part"]))
            or (info["part"] is None and "part" in manifest)):
        raise ValueError(f"Cache identity or status differs: {path}")
    expected = manifest.get("files")
    if not isinstance(expected, list):
        raise ValueError(f"Invalid cache file list: {path}")
    if not cache.exists() and not expected:
        return None
    actual = entries(cache)
    if actual != expected:
        raise ValueError(f"Cache contents differ from manifest: {path}")
    if not any(item["name"] != "CACHEDIR.TAG" for item in actual):
        return None
    return cache.resolve()


def verified_backends(roots, repository):
    if not repository or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository must have owner/name form")
    artifacts = discover(roots)
    backends = []
    for artifact in artifacts:
        cache = verify_artifact(artifact, repository)
        print(f"Verified {artifact}" + (" (no compiler entries)" if cache is None else ""), file=sys.stderr)
        if cache is not None:
            backends.append(cache)
    if not backends:
        raise ValueError("No compiler entries were found in the verified artifacts")
    return backends


def settings(backends, roots, workspace, writable):
    if not workspace.is_dir() or not (workspace / "src").is_dir():
        raise ValueError("Workspace must contain the src checkout")
    if writable.is_symlink() or (writable.exists() and not writable.is_dir()):
        raise ValueError("Writable cache must be a non-symlink directory or a new path")
    workspace, writable = workspace.resolve(), writable.resolve()
    if any(artifact_info(path.name) for path in (writable, *writable.parents)):
        raise ValueError("Writable cache must be separate from downloaded artifacts")
    for root in roots:
        root = root.resolve()
        if writable == root or writable.is_relative_to(root) or root.is_relative_to(writable):
            raise ValueError("Writable cache must be separate from downloaded artifacts")
    storage = " ".join([*(path.as_uri() + "|read-only" for path in backends),
                        (writable / "remote").as_uri()])
    return {"CCACHE_BASEDIR": str(workspace), "CCACHE_DIR": str(writable / "stats"),
            "CCACHE_COMPILERCHECK": "content", "CCACHE_REMOTE_ONLY": "true",
            "CCACHE_NOREADONLY": "true", "CCACHE_NOREADONLY_DIRECT": "true",
            "CCACHE_NODISABLE": "true", "CCACHE_NORECACHE": "true",
            "CCACHE_MAXSIZE": "0", "CCACHE_MAXFILES": "0",
            "CCACHE_REMOTE_STORAGE": storage}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, required=True,
                        help="artifact directory, run directory, or directory of run directories; repeatable")
    parser.add_argument("--repository", required=True, help="artifact repository, e.g. GuangDai/brave-core")
    parser.add_argument("--workspace", type=Path, help="workspace containing src")
    parser.add_argument("--writable-cache", type=Path, help="separate directory for new results")
    parser.add_argument("--check-only", action="store_true", help="verify without emitting shell settings")
    args = parser.parse_args()
    if not args.check_only and (not args.workspace or not args.writable_cache):
        parser.error("--workspace and --writable-cache are required unless --check-only is set")
    if not args.check_only and (platform.system() != "Darwin" or platform.machine() != "arm64"):
        parser.error("Shell settings require an Apple Silicon Mac; --check-only works on other hosts")
    backends = verified_backends(args.root, args.repository)
    if args.check_only:
        print(f"Verified {len(backends)} nonempty read-only cache backend(s).")
        return
    values = settings(backends, args.root, args.workspace, args.writable_cache)
    print("unset CCACHE_NOREMOTE_ONLY")
    for key, value in values.items():
        print(f"export {key}={shlex.quote(value)}")
    print("Ccache checks compiler and input contents; matches are not guaranteed.", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Cache recovery error: {error}", file=sys.stderr)
        sys.exit(1)
