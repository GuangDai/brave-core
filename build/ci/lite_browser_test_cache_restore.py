#!/usr/bin/env python3
"""Safely restore an optional browser-test compiler cache."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from lite_checkpoint import compatible_identity, identity
from lite_browser_checkpoint import OVERLAY_COMMIT, OVERLAY_SHA256, SOURCE
from lite_shard_cache import TARGETS, entries


PREFIX = 'brave-lite-verify-stage-1-shard-5-part-'
POSITIVE = re.compile(r'[1-9][0-9]*\Z')


def selection(run, attempt):
    if not POSITIVE.fullmatch(run) or not POSITIVE.fullmatch(attempt):
        raise ValueError('Run ID and attempt must be positive integers')
    return re.compile(re.escape(PREFIX) + r'([1-4])-a' + re.escape(attempt) + r'\Z')


def preflight(run, attempt, started, now, free, pages):
    pattern = selection(run, attempt)
    if now >= started + 205 * 60:
        return []
    if (not isinstance(pages, list) or not pages or
            not all(isinstance(page, dict) and isinstance(page.get('artifacts'), list)
                    and type(page.get('total_count')) is int for page in pages)):
        raise ValueError('Invalid artifact inventory')
    counts = {page['total_count'] for page in pages}
    artifacts = [item for page in pages for item in page['artifacts']]
    ids = [item.get('id') for item in artifacts if isinstance(item, dict)]
    if (len(counts) != 1 or len(artifacts) != next(iter(counts)) or
            len(ids) != len(artifacts) or any(type(value) is not int or value <= 0 for value in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Artifact inventory is incomplete or duplicated')
    found = []
    for item in artifacts:
        match = pattern.fullmatch(str(item.get('name', '')))
        if not match or item.get('expired') is not False:
            continue
        origin = item.get('workflow_run')
        if (type(item.get('size_in_bytes')) is not int or item['size_in_bytes'] <= 0 or
                not isinstance(origin, dict) or str(origin.get('id')) != run):
            raise ValueError('Artifact size or run differs')
        found.append((int(match.group(1)), item['name'], item['size_in_bytes']))
    if len({part for part, _, _ in found}) != len(found):
        raise ValueError('Duplicate cache part')
    if not found or free < 32 * 1024 ** 3 + 2 * sum(size for _, _, size in found):
        return []
    return [name for _, name, _ in sorted(found, reverse=True)]


def validate_provenance(provenance, current):
    if (not isinstance(provenance, dict) or not isinstance(current, dict)
            or not isinstance(current.get('repository'), str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', current['repository'])
            or current.get('architecture') != 'arm64'
            or provenance.get('test_repository') != current.get('repository')
            or provenance.get('test_architecture') != 'arm64'
            or provenance.get('test_source_commit') != current.get('commit')
            or not isinstance(provenance.get('test_source_commit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', provenance['test_source_commit'])
            or type(provenance.get('test_overlay')) is not bool
            or not isinstance(provenance.get('app_binary_sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', provenance['app_binary_sha256'])
            or not isinstance(provenance.get('verification_workflow_commit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', provenance['verification_workflow_commit'])):
        raise ValueError('Browser verification provenance differs')
    if provenance['test_overlay']:
        if (provenance['test_source_commit'] != SOURCE
                or provenance.get('test_overlay_commit') != OVERLAY_COMMIT
                or provenance.get('test_overlay_sha256') != OVERLAY_SHA256):
            raise ValueError('Browser verification overlay provenance differs')
    elif provenance.get('test_overlay_commit') != '' or provenance.get('test_overlay_sha256') != '':
        raise ValueError('Disabled overlay must have empty provenance')


def verified_backends(root, current, provenance, run, attempt, expected):
    pattern = selection(run, attempt)
    validate_provenance(provenance, current)
    if (root.is_symlink() or not root.is_dir() or not isinstance(expected, list) or not expected
            or any(not isinstance(name, str) or not pattern.fullmatch(name) for name in expected)
            or len(set(expected)) != len(expected)):
        raise ValueError('Invalid downloaded cache selection')
    actual_names = {path.name for path in root.iterdir()}
    if actual_names != set(expected):
        raise ValueError('Downloaded cache parts differ from inventory')
    backends = []
    for name in sorted(expected, key=lambda value: int(pattern.fullmatch(value).group(1)), reverse=True):
        path = root / name
        manifest_path = path / 'manifest.json'
        cache = path / 'cache'
        if (path.is_symlink() or not path.is_dir() or manifest_path.is_symlink()
                or not manifest_path.is_file() or cache.is_symlink()):
            raise ValueError(f'Invalid cache artifact: {name}')
        manifest = json.loads(manifest_path.read_text())
        if (not isinstance(manifest, dict) or type(manifest.get('version')) is not int
                or manifest['version'] != 1 or not compatible_identity(manifest.get('identity'), current)
                or manifest.get('shard') != '5' or manifest.get('target') != TARGETS['5']
                or type(manifest.get('part')) is not int or manifest['part'] != int(pattern.fullmatch(name).group(1))
                or manifest.get('outcome') not in ('complete', 'checkpoint', 'failed')
                or manifest.get('actual_build_target') != 'brave_browser_tests'
                or manifest.get('cache_purpose') != 'browser-verification'):
            raise ValueError(f'Cache identity, target or purpose differs: {name}')
        saved_provenance = manifest.get('verification_provenance')
        validate_provenance(saved_provenance, current)
        matching = ('test_repository', 'test_architecture', 'test_source_commit', 'test_overlay',
                    'test_overlay_commit', 'test_overlay_sha256', 'app_binary_sha256')
        if any(saved_provenance.get(key) != provenance.get(key) for key in matching):
            raise ValueError(f'Cache overlay or application differs: {name}')
        expected_files = manifest.get('files')
        if (not isinstance(expected_files, list) or
                not all(isinstance(item, dict) and set(item) == {'name', 'size', 'sha256'}
                        and isinstance(item['name'], str) and bool(item['name'])
                        and type(item['size']) is int and item['size'] >= 0
                        and isinstance(item['sha256'], str)
                        and re.fullmatch(r'[a-f0-9]{64}', item['sha256'])
                        for item in expected_files)):
            raise ValueError(f'Invalid cache file list: {name}')
        actual_files = entries(cache) if cache.exists() else []
        if actual_files != expected_files:
            raise ValueError(f'Cache contents differ: {name}')
        if actual_files:
            backends.append(cache.resolve().as_uri() + '|read-only')
    if not backends:
        raise ValueError('No reusable compiler entries')
    return backends


def query(repository, run):
    endpoint = f'repos/{repository}/actions/runs/{run}/artifacts?per_page=100'
    output = subprocess.check_output(['gh', 'api', '--paginate', '--slurp', endpoint], text=True, timeout=60)
    return json.loads(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preflight', 'verify'])
    args = parser.parse_args()
    env = os.environ
    run, attempt = env['VERIFY_CACHE_RUN'], env['VERIFY_CACHE_ATTEMPT']
    selection(run, attempt)
    if args.action == 'preflight':
        names = preflight(run, attempt, int(env['LITE_JOB_STARTED']), time.time(),
                          shutil.disk_usage(env['GITHUB_WORKSPACE']).free,
                          query(env['GITHUB_REPOSITORY'], run))
        with Path(env['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
            output.write(f"ready={'true' if names else 'false'}\n")
            output.write('names=' + json.dumps(names, separators=(',', ':')) + '\n')
        print(f'Available verified-test cache parts: {len(names)}', flush=True)
        return
    current = identity(env['GITHUB_REPOSITORY'], env['LITE_SOURCE_COMMIT'], Path(env['GITHUB_WORKSPACE']))
    provenance_path = Path(env['RUNNER_TEMP']) / 'browser-verification/provenance.json'
    if provenance_path.is_symlink() or not provenance_path.is_file():
        raise ValueError('Current browser verification provenance is missing')
    provenance = json.loads(provenance_path.read_text())
    backends = verified_backends(Path(env['RUNNER_TEMP']) / 'lite-browser-verify-cache', current, provenance,
                                 run, attempt, json.loads(env['EXPECTED_CACHE_NAMES']))
    storage = ' '.join(filter(None, [env.get('CCACHE_REMOTE_STORAGE', ''), *backends]))
    with Path(env['GITHUB_ENV']).open('a', encoding='utf-8') as output:
        output.write(f'CCACHE_REMOTE_STORAGE={storage}\n')
    print(f'Enabled {len(backends)} validated read-only browser-test cache part(s)', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'Browser-test cache restore skipped: {error}', file=sys.stderr)
        sys.exit(1)
