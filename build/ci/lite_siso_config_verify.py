#!/usr/bin/env python3
"""Check that a restored build uses the tested ccache-aware Siso override."""

import argparse
from pathlib import Path


def verify(src):
    original = src / "brave/build/config/siso/brave_siso_config.star"
    applied = src / "build/config/siso/brave_siso_config.star"
    source = original.read_bytes()
    if applied.read_bytes() != source:
        raise RuntimeError("The installed Siso configuration differs from Brave's source")
    if (b'"name": "brave_ccache_redirect_cc"' not in source or
            b'"handler": "redirect_cc"' not in source or
            b'"command_prefix": "ccache ../../third_party/llvm-build/Release+Asserts/bin/clang"' not in source):
        raise RuntimeError("The restored source lacks the ccache-aware Siso override")
    print("Verified restored Siso configuration", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    verify(parser.parse_args().src)


if __name__ == "__main__":
    main()
