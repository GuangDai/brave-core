#!/usr/bin/env python3
"""Exercise shared-build workflow plumbing using only synthetic files."""

import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


def main():
    args = sys.argv[1:]
    target = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--target=')), '')
    ninja = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--ninja=')), '')
    group = re.fullmatch(r'brave_lite_group_([1-5])', target)
    if target == 'brave_lite_shared':
        expected_ninja = 'f:brave_lite_shared.ninja'
    elif group:
        expected_ninja = 'f:brave_lite_graph.ninja'
    else:
        raise RuntimeError(f'Unexpected fixture target: {target}')
    if ninja != expected_ninja:
        raise RuntimeError(f'Unexpected fixture Ninja argument: {ninja}')

    env = os.environ
    src = Path(env['GITHUB_WORKSPACE']) / 'src'
    build = src / 'out/Static_arm64'
    if group:
        for backend in env.get('CCACHE_REMOTE_STORAGE', '').split():
            if '|read-only' not in backend:
                continue
            uri = backend.split('|', 1)[0]
            root = Path(unquote(urlsplit(uri).path))
            if (root / 'aa' / f'group-{group.group(1)}').is_file():
                print(f'Reused synthetic group {group.group(1)} cache', flush=True)
                return

    subprocess.run([str(src / 'tools/siso/siso'), 'ninja', '-C', 'out/Static_arm64',
                    target, '-k', '1', '-f', ninja[2:], '--offline',
                    '-cache_dir', str(src / 'siso-cache')], cwd=src, check=True)
    compiled = (build / 'compiled.log').read_text().splitlines()
    if compiled.count('obj/shared.o') != 1:
        raise RuntimeError(f'Shared prerequisite did not survive: {compiled}')
    if group and len([name for name in compiled if name.startswith('obj/leaf')]) != 1:
        raise RuntimeError(f'Unexpected synthetic group outputs: {compiled}')
    cache = Path(env['RUNNER_TEMP']) / 'lite-stage-cache' / 'aa'
    cache.mkdir(parents=True, exist_ok=True)
    (cache / (f'group-{group.group(1)}' if group else 'shared')).write_text(target)
    print(f'Built synthetic target {target}', flush=True)


if __name__ == '__main__':
    main()
