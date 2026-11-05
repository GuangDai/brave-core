#!/usr/bin/env python3
"""Check disk and time before fetching an optional compiler cache."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def eligible(env, free, now, query):
    run, shard, attempt, kind = (env[key] for key in ('RESCUE_RUN', 'RESCUE_SHARD', 'RESCUE_ATTEMPT', 'RESCUE_KIND'))
    stage = env.get('RESCUE_STAGE', '')
    if not run.isdigit() or not re.fullmatch('[1-5]', shard) or not attempt.isdigit():
        raise ValueError('Invalid rescue cache identity')
    if kind == 'stage' and re.fullmatch('[1-8]', stage):
        prefix = f'brave-lite-stage-{stage}-shard-{shard}-part-'
    elif kind == 'shard':
        prefix = f'brave-lite-shard-{shard}-part-'
    else:
        raise ValueError('Invalid rescue cache kind')
    started = int(env['LITE_JOB_STARTED'])
    if now >= started + 205 * 60:
        return False, 'less than 60 minutes remain in the build window'
    pages = query(run)
    total = 0
    count = 0
    pattern = re.compile(re.escape(prefix) + r'[1-4]-a' + re.escape(attempt) + r'\Z')
    for page in pages:
        for item in page['artifacts']:
            if item.get('expired') is False and pattern.fullmatch(str(item.get('name', ''))):
                size = item.get('size_in_bytes')
                if type(size) is not int or size <= 0:
                    raise ValueError('Invalid rescue artifact size')
                total += size
                count += 1
    if not count:
        return False, 'no matching cache artifacts are available'
    if free < 32 * 1024 ** 3 + 2 * total:
        return False, 'disk reserve would be crossed'
    return True, f'{count} cache artifacts; {total} download bytes'


def main():
    env = os.environ
    def query(run):
        endpoint = f"repos/{env['GITHUB_REPOSITORY']}/actions/runs/{run}/artifacts?per_page=100"
        result = subprocess.check_output(['gh', 'api', '--paginate', '--slurp', endpoint], text=True, timeout=60)
        pages = json.loads(result)
        if (not isinstance(pages, list) or not pages
                or not all(isinstance(page, dict) and isinstance(page.get('artifacts'), list)
                           and type(page.get('total_count')) is int for page in pages)):
            raise ValueError('Invalid artifact list')
        totals = {page['total_count'] for page in pages}
        artifacts = [item for page in pages for item in page['artifacts']]
        ids = [item.get('id') for item in artifacts if isinstance(item, dict)]
        if (len(totals) != 1 or len(artifacts) != next(iter(totals))
                or len(ids) != len(artifacts) or len(set(ids)) != len(ids)):
            raise ValueError('Incomplete or duplicated artifact list')
        return pages
    try:
        ready, reason = eligible(env, shutil.disk_usage(env['GITHUB_WORKSPACE']).free, time.time(), query)
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        ready, reason = False, f'cache preflight failed: {error}'
    with Path(env['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
        output.write(f"ready={'true' if ready else 'false'}\n")
    print(f'Optional cache preflight: {reason}', flush=True)


if __name__ == '__main__':
    main()
