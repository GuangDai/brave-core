#!/usr/bin/env python3
"""Guard and record isolated browser-test checkpoints and test-only overlays."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys


KIND = 'brave-lite-browser-verification-v1'
SOURCE = '27eb2693ddf733af196a078740d01f8d2f1d1800'
OVERLAY_COMMIT = 'b9531e4e93032b047a3d45531b60f8ecc24c1df6'
OVERLAY_SHA256 = '5a90080662affaa9d21d7eed8a1d895aec1a44ab62947843e4cb74bd89bd9bde'
# Each pair is the exact Git blob before and after applying the test-only patch.
TEST_BLOBS = {
    'browser/password_manager/password_manager_browsertest.cc': (
        'dc3c7731d1bab823752d7fca74256dd3b9d61cd2',
        'b5542015316e24d0812bd861bebbbf57162f0f95',
    ),
    'browser/translate/brave_translate_browsertest.cc': (
        '5d8c8108184b0fb31c1b9ada7fe8956318b15b38',
        '060298a628f181015055d8aa8008cfdb70dd7927',
    ),
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def validate_checkpoint(manifest, source, overlay, namespace):
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('Invalid source commit')
    identity = manifest.get('identity')
    if (not isinstance(identity, dict) or identity.get('commit') != source
            or identity.get('architecture') != 'arm64'
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', str(identity.get('repository', '')))):
        raise ValueError('Checkpoint source differs')
    kind = manifest.get('checkpoint_kind')
    if namespace == 'brave-lite':
        if kind is not None or type(manifest.get('build_phase')) is not int \
                or not 6 <= manifest['build_phase'] <= 8 or manifest.get('phase_complete') is not True:
            raise ValueError('Expected a completed browser application checkpoint')
    elif namespace == 'brave-lite-verify':
        if (kind != KIND or manifest.get('test_source_commit') != source
                or manifest.get('test_repository') != identity['repository']
                or manifest.get('test_architecture') != 'arm64'
                or manifest.get('test_overlay') is not overlay
                or manifest.get('test_overlay_commit') != (OVERLAY_COMMIT if overlay else '')
                or manifest.get('test_overlay_sha256') != (OVERLAY_SHA256 if overlay else '')
                or not re.fullmatch(r'[0-9a-f]{40}', str(manifest.get('verification_workflow_commit', '')))
                or not re.fullmatch(r'[0-9a-f]{64}', str(manifest.get('app_binary_sha256', '')))):
            raise ValueError('Browser verification checkpoint provenance differs')
    else:
        raise ValueError('Invalid checkpoint namespace')
    if overlay and source != SOURCE:
        raise ValueError('Browser test overlay requires the pinned source commit')


def app_digest(workspace):
    build = workspace / 'src/out/Static_arm64'
    apps = [path for path in build.glob('*.app') if path.is_dir()]
    if len(apps) != 1:
        raise ValueError('Expected exactly one application in the checkpoint')
    with (apps[0] / 'Contents/Info.plist').open('rb') as stream:
        executable = plistlib.load(stream)['CFBundleExecutable']
    if not isinstance(executable, str) or Path(executable).name != executable:
        raise ValueError('Invalid application executable name')
    binary = apps[0] / 'Contents/MacOS' / executable
    if not binary.is_file():
        raise ValueError('Application executable is missing')
    return sha256(binary)


def prepare_overlay(brave, source, enabled, patch_path):
    if not enabled:
        subprocess.run(['git', 'diff', 'HEAD', '--quiet', '--', *TEST_BLOBS], cwd=brave, check=True)
        return ''
    patch = base64.b64decode(patch_path.read_bytes().strip(), validate=True)
    if source != SOURCE or hashlib.sha256(patch).hexdigest() != OVERLAY_SHA256:
        raise ValueError('Browser test overlay identity differs')

    def blobs():
        return tuple(subprocess.check_output(['git', 'hash-object', str(brave / path)],
                                             cwd=brave, text=True).strip()
                     for path in TEST_BLOBS)

    original = tuple(pair[0] for pair in TEST_BLOBS.values())
    applied = tuple(pair[1] for pair in TEST_BLOBS.values())
    current = blobs()
    if current == original:
        subprocess.run(['git', 'apply', '--check', '-'], cwd=brave, input=patch, check=True)
        subprocess.run(['git', 'apply', '-'], cwd=brave, input=patch, check=True)
    elif current != applied:
        raise ValueError('Browser test sources do not match either pinned version')
    if blobs() != applied:
        raise ValueError('Applied browser test overlay differs')
    return OVERLAY_SHA256


def prepare(workspace, manifest, source, overlay, namespace, patch_path, provenance):
    validate_checkpoint(manifest, source, overlay, namespace)
    digest = app_digest(workspace)
    if namespace == 'brave-lite-verify' and digest != manifest['app_binary_sha256']:
        raise ValueError('Application executable differs from the test checkpoint')
    overlay_hash = prepare_overlay(workspace / 'src/brave', source, overlay, patch_path)
    workflow_commit = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch(r'[0-9a-f]{40}', workflow_commit):
        raise ValueError('Verification workflow commit is missing or invalid')
    data = {'test_repository': manifest['identity']['repository'], 'test_architecture': 'arm64',
            'test_source_commit': source, 'test_overlay': overlay,
            'test_overlay_commit': OVERLAY_COMMIT if overlay else '',
            'test_overlay_sha256': overlay_hash, 'app_binary_sha256': digest,
            'verification_workflow_commit': workflow_commit}
    provenance.write_text(json.dumps(data, indent=2) + '\n')
    print('Verified browser checkpoint and isolated test provenance', flush=True)


def record(manifest_path, provenance_path, compile_outcome, reason):
    manifest = json.loads(manifest_path.read_text())
    data = json.loads(provenance_path.read_text())
    if compile_outcome not in ('complete', 'checkpoint', 'failed'):
        raise ValueError('Invalid test compile outcome')
    manifest.update({**data, 'checkpoint_kind': KIND,
                     'test_compile_outcome': compile_outcome, 'test_compile_reason': reason})
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    start = sub.add_parser('prepare')
    start.add_argument('--workspace', type=Path, required=True)
    start.add_argument('--manifest', type=Path, required=True)
    start.add_argument('--source', required=True)
    start.add_argument('--overlay', choices=['true', 'false'], required=True)
    start.add_argument('--namespace', choices=['brave-lite', 'brave-lite-verify'], required=True)
    start.add_argument('--patch', type=Path, required=True)
    start.add_argument('--provenance', type=Path, required=True)
    check = sub.add_parser('check-app')
    check.add_argument('--workspace', type=Path, required=True)
    check.add_argument('--provenance', type=Path, required=True)
    end = sub.add_parser('record')
    end.add_argument('--manifest', type=Path, required=True)
    end.add_argument('--provenance', type=Path, required=True)
    end.add_argument('--outcome', required=True)
    end.add_argument('--reason', default='')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.workspace, json.loads(args.manifest.read_text()), args.source,
                args.overlay == 'true', args.namespace, args.patch, args.provenance)
    elif args.action == 'check-app':
        if app_digest(args.workspace) != json.loads(args.provenance.read_text())['app_binary_sha256']:
            raise ValueError('Application executable changed while building tests')
        print('Application executable is unchanged', flush=True)
    else:
        record(args.manifest, args.provenance, args.outcome, args.reason)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'Browser checkpoint error: {error}', file=sys.stderr)
        sys.exit(1)
