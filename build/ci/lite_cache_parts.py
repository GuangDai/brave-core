#!/usr/bin/env python3
"""Save incremental ccache shards and validate any surviving parts."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from lite_checkpoint import identity
from lite_shard_cache import TARGETS, entries


MAX_PARTS = 4


def save(cache, stage, state_path, build_identity, shard, part, outcome, reason):
    if (shard not in TARGETS or not 1 <= part <= MAX_PARTS
            or outcome not in ("complete", "checkpoint", "failed")):
        raise ValueError("Invalid shard, part or build outcome")
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    if not isinstance(previous, dict):
        raise RuntimeError("Invalid previous cache state")
    files = entries(cache)
    changed = [item for item in files if previous.get(item["name"]) != item["sha256"]]
    stage.mkdir(parents=True, exist_ok=False)
    for item in changed:
        destination = stage / "cache" / item["name"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(cache / item["name"], destination, follow_symlinks=False)
    manifest = {"version": 1, "identity": build_identity, "shard": shard,
                "target": TARGETS[shard], "part": part, "outcome": outcome,
                "reason": reason, "files": changed}
    (stage / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")) + "\n")
    state_path.write_text(json.dumps({item["name"]: item["sha256"] for item in files}) + "\n")
    print(f"Saved shard {shard} part {part}: {len(changed)} files, "
          f"{sum(item['size'] for item in changed)} bytes", flush=True)


def verify(root, build_identity, shard, attempt):
    if shard not in TARGETS or not attempt.isdigit():
        raise ValueError("Invalid shard or attempt")
    backends = []
    for part in range(MAX_PARTS, 0, -1):
        path = root / f"brave-lite-shard-{shard}-part-{part}-a{attempt}"
        if not path.exists():
            continue
        manifest = json.loads((path / "manifest.json").read_text())
        old = manifest.get("identity")
        if (manifest.get("version") != 1 or not isinstance(old, dict)
                or old.get("repository") != build_identity.get("repository")
                or old.get("architecture") != build_identity.get("architecture")
                or manifest.get("shard") != shard or manifest.get("target") != TARGETS[shard]
                or manifest.get("part") != part
                or manifest.get("outcome") not in ("complete", "checkpoint", "failed")):
            raise RuntimeError(f"Shard {shard} part {part} identity or status differs")
        actual = entries(path / "cache") if (path / "cache").exists() else []
        if actual != manifest.get("files"):
            raise RuntimeError(f"Shard {shard} part {part} failed verification")
        if actual:
            backends.append(f"{(path / 'cache').resolve().as_uri()}|read-only")
        print(f"Verified shard {shard} part {part}: {len(actual)} files, "
              f"{sum(item['size'] for item in actual)} bytes", flush=True)
    return " ".join(backends)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["save", "verify"])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--shard", required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--part", type=int)
    parser.add_argument("--outcome")
    parser.add_argument("--reason", default="")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--attempt")
    parser.add_argument("--portable", action="store_true")
    args = parser.parse_args()
    build_identity = identity(args.repository, args.commit, args.workspace,
                              require_runner=not args.portable)
    if args.action == "save":
        if not all((args.cache, args.stage, args.state, args.part)):
            parser.error("save requires cache, stage, state and part")
        save(args.cache, args.stage, args.state, build_identity, args.shard,
             args.part, args.outcome, args.reason)
    else:
        if not args.root or not args.attempt:
            parser.error("verify requires root and attempt")
        backends = verify(args.root, build_identity, args.shard, args.attempt)
        settings = (f"CCACHE_REMOTE_STORAGE={backends}\nCCACHE_REMOTE_ONLY=true\n"
                    if backends else "CCACHE_DISABLE=true\n")
        if output := os.environ.get("GITHUB_ENV"):
            with open(output, "a", encoding="utf-8") as env:
                env.write(settings)
        elif backends:
            print(f"export CCACHE_REMOTE_STORAGE={shlex.quote(backends)}")
            print("export CCACHE_REMOTE_ONLY=true")
        else:
            print("No compiler entries survived in the available cache parts.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Shard part error: {error}", file=sys.stderr)
        sys.exit(1)
