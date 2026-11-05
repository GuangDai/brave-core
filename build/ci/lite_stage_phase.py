#!/usr/bin/env python3
"""Resume an unfinished build phase without repeating completed phases."""

import argparse
import json
from pathlib import Path


def next_phase(manifest, fallback):
    phase = manifest.get("build_phase", fallback)
    # Old manifests did not record whether the target finished. Rechecking that
    # target is incremental and also resumes work that was interrupted.
    complete = manifest.get("phase_complete", False)
    if type(phase) is not int or not 1 <= phase <= 8 or type(complete) is not bool:
        raise ValueError("Invalid build phase metadata")
    return min(phase + int(complete), 8)


def record_phase(manifest, phase, complete):
    if type(phase) is not int or not 1 <= phase <= 8 or type(complete) is not bool:
        raise ValueError("Invalid build phase metadata")
    return {**manifest, "build_phase": phase, "phase_complete": complete}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["next", "record"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--complete", choices=["true", "false"], default="false")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if args.action == "next":
        print(next_phase(manifest, args.phase))
    else:
        manifest = record_phase(manifest, args.phase, args.complete == "true")
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
