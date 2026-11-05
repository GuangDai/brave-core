#!/usr/bin/env python3
"""Check macOS build flags and exercise the built browser headlessly."""

import argparse
from pathlib import Path
import plistlib
import re
import subprocess
import sys


FLAGS = {
    "brave/components/ai_chat/core/common/buildflags/buildflags.h": "ENABLE_AI_CHAT",
    "brave/components/brave_rewards/core/buildflags/buildflags.h": "ENABLE_BRAVE_REWARDS",
    "brave/components/brave_vpn/common/buildflags/buildflags.h": "ENABLE_BRAVE_VPN",
    "brave/components/brave_wallet/common/buildflags/buildflags.h": "ENABLE_BRAVE_WALLET",
}


def verify(build, profile):
    for header, flag in FLAGS.items():
        path = build / "gen" / header
        value = path.read_text()
        expected = rf"^#define BUILDFLAG_INTERNAL_{flag}\(\) \(0\)$"
        if not re.search(expected, value, flags=re.MULTILINE):
            raise RuntimeError(f"{flag} was not compiled out: {path}")
        print(f"{flag}=0", flush=True)

    apps = list(build.glob("*.app"))
    if len(apps) != 1:
        raise RuntimeError(f"Expected one macOS app, found {apps}")
    app = apps[0]
    with (app / "Contents" / "Info.plist").open("rb") as stream:
        executable = plistlib.load(stream)["CFBundleExecutable"]
    browser = app / "Contents" / "MacOS" / executable
    print(subprocess.check_output([str(browser), "--version"], text=True,
                                  timeout=60).strip(), flush=True)
    marker = "brave-lite-smoke-ok"
    result = subprocess.run(
        [str(browser), "--headless", "--disable-gpu", "--no-first-run",
         "--disable-background-networking", f"--user-data-dir={profile}",
         "--dump-dom", f"data:text/html,<p>{marker}</p>"],
        capture_output=True, text=True, timeout=120, check=True,
    )
    if marker not in result.stdout:
        raise RuntimeError("The headless browser did not render the smoke page")
    print("Headless browser smoke test passed", flush=True)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    verify(args.build, args.profile)


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Build verification error: {error}", file=sys.stderr)
        sys.exit(1)
