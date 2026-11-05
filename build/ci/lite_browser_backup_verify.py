#!/usr/bin/env python3
"""Verify downloaded browser-verification artifacts without executing them."""

import argparse
import json
from pathlib import Path
import re
import sys

import lite_browser_checkpoint as checkpoint
import lite_browser_report as report
import lite_browser_verify as browser
from lite_shard_cache import TARGETS, entries


CACHE = re.compile(r'brave-lite-verify-stage-1-shard-5-part-([1-4])-a([1-9][0-9]*)\Z')
MANIFEST = re.compile(r'brave-lite-verify-s1-a([1-9][0-9]*)-manifest\Z')
VOLUME = re.compile(r'brave-lite-verify-s1-a([1-9][0-9]*)-(part-a[a-p])\Z')
RESULTS = re.compile(r'brave-lite-browser-test-results-a([1-9][0-9]*)\Z')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
RESULT_KIND = 'brave-lite-browser-test-results-v1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    require(not path.is_symlink() and path.is_file(), f'Missing or invalid file: {path}')
    data = json.loads(path.read_text())
    require(isinstance(data, dict), f'Expected a JSON object: {path}')
    return data


def directory(path):
    require(not path.is_symlink() and path.is_dir(), f'Missing or invalid directory: {path}')


def context(repository, source, workflow, app_sha256, overlay):
    require(bool(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)), 'Invalid repository')
    require(bool(HEX40.fullmatch(source)) and bool(HEX40.fullmatch(workflow)), 'Invalid commit')
    require(bool(HEX64.fullmatch(app_sha256)) and type(overlay) is bool, 'Invalid app digest or overlay')
    if overlay:
        require(source == checkpoint.SOURCE, 'Overlay requires the pinned source commit')
    return {'test_repository': repository, 'test_architecture': 'arm64',
            'test_source_commit': source, 'test_overlay': overlay,
            'test_overlay_commit': checkpoint.OVERLAY_COMMIT if overlay else '',
            'test_overlay_sha256': checkpoint.OVERLAY_SHA256 if overlay else '',
            'app_binary_sha256': app_sha256, 'verification_workflow_commit': workflow}


def provenance(data, expected):
    require(isinstance(data, dict), 'Invalid provenance')
    for key, value in expected.items():
        require(type(data.get(key)) is type(value) and data.get(key) == value,
                f'Provenance differs: {key}')


def identity(data, expected):
    require(isinstance(data, dict) and data.get('repository') == expected['test_repository']
            and data.get('commit') == expected['test_source_commit']
            and data.get('architecture') == expected['test_architecture'],
            'Repository, source or architecture differs')


def file_list(data):
    require(isinstance(data, list), 'Invalid file list')
    names = []
    for item in data:
        require(isinstance(item, dict) and set(item) == {'name', 'size', 'sha256'}
                and isinstance(item['name'], str) and bool(item['name'])
                and type(item['size']) is int and item['size'] >= 0
                and isinstance(item['sha256'], str) and bool(HEX64.fullmatch(item['sha256'])),
                'Invalid file entry')
        names.append(item['name'])
    require(len(names) == len(set(names)), 'Duplicate file entries')
    return data


def verify_cache(path, expected):
    directory(path)
    match = CACHE.fullmatch(path.name)
    require(match is not None, 'Invalid browser-verification cache name')
    data = read_json(path / 'manifest.json')
    require(type(data.get('version')) is int and data['version'] == 1, 'Invalid cache version')
    identity(data.get('identity'), expected)
    provenance(data.get('verification_provenance'), expected)
    require(data.get('shard') == '5' and data.get('target') == TARGETS['5']
            and type(data.get('part')) is int and data['part'] == int(match.group(1))
            and data.get('actual_build_target') == 'brave_browser_tests'
            and data.get('cache_purpose') == 'browser-verification'
            and data.get('outcome') in ('complete', 'checkpoint', 'failed'),
            'Cache target, purpose or status differs')
    files = file_list(data.get('files'))
    cache = path / 'cache'
    require(not cache.is_symlink(), 'Cache directory is a symlink')
    actual = entries(cache) if cache.exists() else []
    require(actual == files, 'Cache files differ from manifest')
    require({item.name for item in path.iterdir()} == ({'manifest.json', 'cache'} if cache.exists() else {'manifest.json'}),
            'Unexpected cache artifact contents')
    return {'kind': 'cache', 'part': int(match.group(1)), 'attempt': int(match.group(2)),
            'files': len(files)}


def verify_checkpoint_manifest(path, expected):
    directory(path)
    match = MANIFEST.fullmatch(path.name)
    require(match is not None, 'Invalid checkpoint manifest name')
    require({item.name for item in path.iterdir()} == {'manifest.json'}, 'Unexpected manifest contents')
    data = read_json(path / 'manifest.json')
    require(type(data.get('version')) is int and data['version'] == 1, 'Invalid checkpoint version')
    identity(data.get('identity'), expected)
    provenance(data, expected)
    require(data.get('checkpoint_kind') == checkpoint.KIND
            and data.get('test_compile_outcome') in ('complete', 'checkpoint', 'failed')
            and isinstance(data.get('test_compile_reason'), str), 'Checkpoint kind or status differs')
    volumes = data.get('volumes')
    require(isinstance(volumes, list) and 1 <= len(volumes) <= 16, 'Invalid checkpoint volumes')
    for index, volume in enumerate(volumes):
        name = f'part-a{chr(ord("a") + index)}'
        require(isinstance(volume, dict) and set(volume) == {'name', 'size', 'sha256'}
                and volume.get('name') == name and type(volume.get('size')) is int and volume['size'] > 0
                and isinstance(volume.get('sha256'), str) and bool(HEX64.fullmatch(volume['sha256'])),
                'Invalid checkpoint volume metadata')
    return data


def verify_checkpoint_volume(path, manifest_dir, expected):
    directory(path)
    match = VOLUME.fullmatch(path.name)
    require(match is not None, 'Invalid checkpoint volume name')
    manifest_match = MANIFEST.fullmatch(manifest_dir.name)
    require(manifest_match is not None and match.group(1) == manifest_match.group(1),
            'Checkpoint volume attempt differs')
    data = verify_checkpoint_manifest(manifest_dir, expected)
    name = match.group(2)
    volume = next((item for item in data['volumes'] if item['name'] == name), None)
    require(volume is not None, 'Checkpoint volume is absent from manifest')
    require({item.name for item in path.iterdir()} == {name}, f'Unexpected volume contents: {path.name}')
    part = path / name
    require(not part.is_symlink() and part.is_file() and part.stat().st_size == volume['size']
            and checkpoint.sha256(part) == volume['sha256'], f'Checkpoint volume differs: {name}')
    return {'kind': 'checkpoint-volume', 'attempt': int(match.group(1)), 'name': name}


def verify_checkpoint(root, attempt, expected):
    directory(root)
    require(isinstance(attempt, str) and bool(re.fullmatch(r'[1-9][0-9]*', attempt)), 'Invalid attempt')
    manifest_dir = root / f'brave-lite-verify-s1-a{attempt}-manifest'
    data = verify_checkpoint_manifest(manifest_dir, expected)
    expected_names = set()
    for volume in data['volumes']:
        dirname = f'brave-lite-verify-s1-a{attempt}-{volume["name"]}'
        expected_names.add(dirname)
        verify_checkpoint_volume(root / dirname, manifest_dir, expected)
    pattern = re.compile(rf'brave-lite-verify-s1-a{re.escape(attempt)}-part-a[a-p]\Z')
    actual_names = {item.name for item in root.iterdir() if pattern.fullmatch(item.name)}
    require(actual_names == expected_names, 'Unexpected or missing checkpoint volume')
    return {'kind': 'checkpoint', 'attempt': int(attempt), 'volumes': len(data['volumes']),
            'compile_outcome': data['test_compile_outcome']}


def verify_results(path, expected):
    directory(path)
    match = RESULTS.fullmatch(path.name)
    require(match is not None, 'Invalid browser-verification results name')
    manifest = read_json(path / report.MANIFEST)
    require(type(manifest.get('version')) is int and manifest['version'] == 1
            and manifest.get('kind') == RESULT_KIND, 'Results kind or version differs')
    provenance(read_json(path / 'provenance.json'), expected)
    files = file_list(manifest.get('files'))
    require(report.entries(path) == files, 'Result files differ from checksum manifest')
    outcome, reason = manifest.get('compile_outcome'), manifest.get('compile_reason')
    app_check, test_status = manifest.get('app_check'), manifest.get('test_status')
    require(outcome in report.COMPILE and isinstance(reason, str)
            and app_check in report.STATUS and test_status in report.STATUS, 'Invalid result statuses')
    if outcome == 'complete':
        require(bool(app_check) and bool(test_status), 'Missing completed build statuses')
    else:
        require(test_status in ('', 'skipped'), 'Tests ran before compilation completed')
    if test_status == 'success':
        require(outcome == 'complete' and app_check == 'success', 'Success contradicts other statuses')
        needed = {'provenance.json', 'controller.log', 'results/expected-tests.json',
                  'results/list.stdout.log', 'results/list.stderr.log', 'results/run.stdout.log',
                  'results/run.stderr.log', 'results/summary.json'}
        require(needed <= {item['name'] for item in files}, 'Successful test evidence is incomplete')
        requested = json.loads((path / 'results/expected-tests.json').read_text())
        tests = browser.selected_tests(expected['test_overlay'])
        require(requested == list(tests), 'Expected test list differs')
        listed = browser.parse_test_list((path / 'results/list.stdout.log').read_text(errors='replace'))
        require(set(tests) <= listed, 'Test listing is incomplete')
        browser.verify_summary(read_json(path / 'results/summary.json'), tests)
    return {'kind': 'results', 'attempt': int(match.group(1)), 'compile_outcome': outcome,
            'app_check': app_check, 'test_status': test_status, 'files': len(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['cache', 'checkpoint', 'results'])
    parser.add_argument('--path', type=Path, required=True,
                        help='artifact directory, or parent containing checkpoint manifest and volumes')
    parser.add_argument('--repository', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--workflow', required=True)
    parser.add_argument('--app-sha256', required=True)
    parser.add_argument('--overlay', choices=['true', 'false'], required=True)
    parser.add_argument('--attempt', help='checkpoint attempt')
    args = parser.parse_args()
    expected = context(args.repository, args.source, args.workflow, args.app_sha256, args.overlay == 'true')
    if args.kind == 'cache':
        result = verify_cache(args.path, expected)
    elif args.kind == 'checkpoint':
        result = verify_checkpoint(args.path, args.attempt, expected)
    else:
        result = verify_results(args.path, expected)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f'Browser backup verification error: {error}', file=sys.stderr)
        sys.exit(1)
