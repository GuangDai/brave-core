#!/usr/bin/env python3
"""Verify compiler-cache shards before handing them to the final build."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from lite_checkpoint import digest, identity


TARGETS = {
    "1": "v8:v8",
    "2": "third_party/blink/renderer/core:core",
    "3": "third_party/blink/renderer/modules:modules",
    "4": "content/browser:browser",
    "5": "chrome/browser:browser",
}
MANIFEST = "manifest.json"


def entries(cache):
    if not cache.is_dir() or cache.is_symlink():
        raise RuntimeError(f"Missing cache directory: {cache}")
    result = []
    for path in sorted(cache.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Unexpected cache symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError(f"Unexpected cache entry: {path}")
        result.append({"name": path.relative_to(cache).as_posix(),
                       "size": path.stat().st_size, "sha256": digest(path)})
    return result


def save(root, build_identity, shard, target, outcome, reason):
    if TARGETS.get(shard) != target or outcome not in ("complete", "checkpoint", "failed"):
        raise ValueError("Invalid shard, target or outcome")
    files = entries(root / "cache")
    if not any(item["name"] != "CACHEDIR.TAG" for item in files):
        raise RuntimeError("The compiler cache contains no compilation results")
    manifest = {"version": 1, "identity": build_identity, "shard": shard,
                "target": target, "outcome": outcome, "reason": reason,
                "files": files}
    (root / MANIFEST).write_text(json.dumps(manifest, separators=(",", ":")) + "\n")
    print(f"Shard {shard}: {len(files)} files, {sum(f['size'] for f in files)} bytes", flush=True)


def verify_one(root, build_identity, attempt, shard):
    if not attempt.isdigit() or shard not in TARGETS:
        raise ValueError("Invalid attempt or shard")
    path = root / f"brave-lite-shard-{shard}-a{attempt}"
    manifest = json.loads((path / MANIFEST).read_text())
    saved_identity = manifest.get("identity")
    if (manifest.get("version") != 1 or not isinstance(saved_identity, dict)
            or saved_identity.get("repository") != build_identity.get("repository")
            or saved_identity.get("architecture") != build_identity.get("architecture")
            or manifest.get("shard") != shard or manifest.get("target") != TARGETS[shard]
            or manifest.get("outcome") not in ("complete", "checkpoint", "failed")):
        raise RuntimeError(f"Shard {shard} identity or status differs")
    actual = entries(path / "cache")
    if not actual or actual != manifest.get("files"):
        raise RuntimeError(f"Shard {shard} cache failed verification")
    print(f"Verified shard {shard}: {len(actual)} files, "
          f"{sum(f['size'] for f in actual)} bytes", flush=True)
    if saved_identity != build_identity:
        print(f"Shard {shard} was produced by commit {saved_identity.get('commit')} "
              f"and image {saved_identity.get('image_version')}; ccache checks compiler "
              "and input content before reuse", flush=True)
    return f"{(path / 'cache').resolve().as_uri()}|read-only"


def verify_set(root, build_identity, attempt):
    return " ".join(verify_one(root, build_identity, attempt, shard) for shard in TARGETS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["save", "verify-one", "verify-set"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--shard")
    parser.add_argument("--target")
    parser.add_argument("--outcome")
    parser.add_argument("--reason", default="")
    parser.add_argument("--attempt")
    parser.add_argument("--portable", action="store_true",
                        help="allow a physical Mac without GitHub runner metadata")
    args = parser.parse_args()
    build_identity = identity(args.repository, args.commit, args.workspace,
                              require_runner=not args.portable)
    if args.action == "save":
        save(args.root, build_identity, args.shard, args.target, args.outcome, args.reason)
    else:
        if args.action == "verify-one":
            backend = verify_one(args.root, build_identity, args.attempt or "", args.shard)
        else:
            backend = verify_set(args.root, build_identity, args.attempt or "")
        if output := os.environ.get("GITHUB_ENV"):
            with open(output, "a", encoding="utf-8") as env:
                env.write(f"CCACHE_REMOTE_STORAGE={backend}\nCCACHE_REMOTE_ONLY=true\n")
        else:
            print(f"export CCACHE_REMOTE_STORAGE={shlex.quote(backend)}")
            print("export CCACHE_REMOTE_ONLY=true")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Shard cache error: {error}", file=sys.stderr)
        sys.exit(1)
