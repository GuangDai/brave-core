#!/usr/bin/env python3
"""Resume an unfinished build phase without repeating completed phases."""

import argparse
import json
from pathlib import Path


def next_phase(manifest, fallback, shared_assembly=False):
    if shared_assembly:
        if manifest.get("shared_complete") is not True:
            raise ValueError("Shared prerequisites are not complete")
        assembly_started = manifest.get("shared_assembly", False)
        if type(assembly_started) is not bool:
            raise ValueError("Invalid shared assembly metadata")
        if not assembly_started:
            return 1
    phase = manifest.get("build_phase", fallback)
    # Old manifests did not record whether the target finished. Rechecking that
    # target is incremental and also resumes work that was interrupted.
    complete = manifest.get("phase_complete", False)
    if type(phase) is not int or not 1 <= phase <= 8 or type(complete) is not bool:
        raise ValueError("Invalid build phase metadata")
    return min(phase + int(complete), 8)


def record_phase(manifest, phase, complete, mode="normal"):
    if type(phase) is not int or not 1 <= phase <= 8 or type(complete) is not bool:
        raise ValueError("Invalid build phase metadata")
    if mode not in ("normal", "bootstrap", "assembly"):
        raise ValueError("Invalid build phase mode")
    result = {**manifest, "build_phase": phase,
              "phase_complete": complete if mode != "bootstrap" else False}
    if mode in ("bootstrap", "assembly"):
        result["shared_complete"] = complete if mode == "bootstrap" else True
        result["shared_assembly"] = mode == "assembly"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["next", "record"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--complete", choices=["true", "false"], default="false")
    parser.add_argument("--mode", choices=["normal", "bootstrap", "assembly"], default="normal")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if args.action == "next":
        print(next_phase(manifest, args.phase, shared_assembly=args.mode == "assembly"))
    else:
        manifest = record_phase(manifest, args.phase, args.complete == "true", args.mode)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
