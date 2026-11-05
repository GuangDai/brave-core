#!/usr/bin/env python3
"""Record checksums and explicit outcomes for isolated browser-test results."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import lite_browser_checkpoint as checkpoint


MANIFEST = 'checksums.json'
STATUS = {'success', 'failure', 'skipped', ''}
COMPILE = {'complete', 'checkpoint', 'failed'}


def entries(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Report root must be a real directory')
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Unexpected report symlink: {path}')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f'Unexpected report entry: {path}')
        name = path.relative_to(root).as_posix()
        if name == MANIFEST:
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while block := stream.read(8 * 1024 * 1024):
                digest.update(block)
        files.append({'name': name, 'size': path.stat().st_size, 'sha256': digest.hexdigest()})
    return files


def record(root, compile_outcome, reason, app_check, test_status):
    if compile_outcome not in COMPILE or app_check not in STATUS or test_status not in STATUS:
        raise ValueError('Invalid verification status')
    if compile_outcome == 'complete' and (not app_check or not test_status):
        raise ValueError('A completed test build needs explicit app and test statuses')
    if compile_outcome != 'complete' and test_status not in ('', 'skipped'):
        raise ValueError('Browser tests cannot run before compilation finishes')
    provenance = json.loads((root / 'provenance.json').read_text())
    if (not isinstance(provenance, dict)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', str(provenance.get('test_repository', '')))
            or provenance.get('test_architecture') != 'arm64'
            or not re.fullmatch(r'[0-9a-f]{40}', str(provenance.get('test_source_commit', '')))
            or type(provenance.get('test_overlay')) is not bool
            or not re.fullmatch(r'[0-9a-f]{40}', str(provenance.get('verification_workflow_commit', '')))
            or not re.fullmatch(r'[0-9a-f]{64}', str(provenance.get('app_binary_sha256', '')))):
        raise ValueError('Missing verification provenance')
    overlay = provenance['test_overlay']
    if (provenance.get('test_overlay_commit') != (checkpoint.OVERLAY_COMMIT if overlay else '')
            or provenance.get('test_overlay_sha256') != (checkpoint.OVERLAY_SHA256 if overlay else '')
            or (overlay and provenance['test_source_commit'] != checkpoint.SOURCE)):
        raise ValueError('Verification overlay provenance differs')
    files = entries(root)
    if not any(item['name'] == 'provenance.json' for item in files):
        raise ValueError('Missing provenance file')
    manifest = {'version': 1, 'kind': 'brave-lite-browser-test-results-v1',
                'compile_outcome': compile_outcome, 'compile_reason': reason,
                'app_check': app_check, 'test_status': test_status, 'files': files}
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Recorded {len(files)} verification result files', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--compile-outcome', required=True)
    parser.add_argument('--reason', default='')
    parser.add_argument('--app-check', default='')
    parser.add_argument('--test-status', default='')
    args = parser.parse_args()
    record(args.root, args.compile_outcome, args.reason, args.app_check, args.test_status)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f'Browser report error: {error}', file=sys.stderr)
        sys.exit(1)
