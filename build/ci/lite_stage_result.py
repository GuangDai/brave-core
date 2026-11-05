#!/usr/bin/env python3
"""Summarize the latest completed cache part for the stage controller."""

import os
from pathlib import Path
import sys


def summarize(target, parts):
    for part in reversed(parts):
        outcome = part.get("outcome", "")
        reason = part.get("reason", "")
        if outcome:
            if outcome not in ("complete", "checkpoint", "failed"):
                raise ValueError("Unexpected compiler outcome")
            break
        if part.get("status") == "failure":
            outcome, reason = "failed", ""
            break
    else:
        raise ValueError("No compiler part produced an outcome")
    stage_outcome = "checkpoint" if target and outcome == "complete" else outcome
    stage_reason = "next" if target and outcome == "complete" else reason
    return {"compile_outcome": outcome, "outcome": stage_outcome, "reason": stage_reason}


def main():
    env = os.environ
    parts = [{key: env.get(f"{key.upper()}_{number}", "")
              for key in ("outcome", "reason", "status")} for number in range(1, 5)]
    result = summarize(env.get("LITE_BUILD_TARGET", ""), parts)
    text = "".join(f"{key}={value}\n" for key, value in result.items())
    if output := env.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"Stage result error: {error}", file=sys.stderr)
        sys.exit(1)
