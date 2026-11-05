#!/usr/bin/env python3
"""Upgrade only the reviewed source patches after restoring an old checkpoint."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PATCH_TARGETS = {
    'patches/chrome-browser-password_manager-chrome_password_manager_client.cc.patch': 'chrome/browser/password_manager/chrome_password_manager_client.cc',
    'patches/components-autofill-core-common-autofill_prefs.cc.patch': 'components/autofill/core/common/autofill_prefs.cc',
    'patches/components-translate-core-browser-translate_prefs.cc.patch': 'components/translate/core/browser/translate_prefs.cc',
    'patches/chrome-browser-ui-autofill-chrome_autofill_client.cc.patch': 'chrome/browser/ui/autofill/chrome_autofill_client.cc',
    'patches/components-autofill-core-browser-foundations-browser_autofill_manager.cc.patch': 'components/autofill/core/browser/foundations/browser_autofill_manager.cc',
}
REVIEWED_SOURCE_FILES = {
    'browser/brave_autofill_browsertest.cc',
    'browser/resources/settings/br/settings_menu.ts',
    'browser/ui/toolbar/brave_app_menu_model.cc',
    'browser/ui/toolbar/brave_app_menu_model_browsertest.cc',
    'chromium_src/chrome/browser/ui/webui/chrome_web_ui_configs.cc',
}


def run(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_diff(repo, old, new):
    if not all(re.fullmatch(r'[0-9a-f]{40}', c) for c in (old, new)) or old == new:
        raise ValueError('Expected two different full commit IDs')
    changes = run(repo, 'diff', '--name-status', '--no-renames', old, new).splitlines()
    patches = []
    for change in changes:
        status, path = change.split('\t', 1)
        if path in PATCH_TARGETS and status in ('M', 'D'):
            patches.append((path, status))
        elif path in REVIEWED_SOURCE_FILES and status in ('M', 'D'):
            continue
        elif path.startswith(('.github/', 'build/ci/', 'docs/')):
            continue
        else:
            raise ValueError(f'Unreviewed source change: {change}')
    if not patches:
        raise ValueError('No reviewed source patch was changed')
    return sorted(patches)


def validate_patches(repo, chromium, patches):
    for patch, status in patches:
        expected = PATCH_TARGETS[patch]
        info_path = (repo / patch).with_suffix('.patchinfo')
        if status == 'D':
            if info_path.exists():
                raise RuntimeError(f'Obsolete patch metadata remains: {patch}')
            baseline = subprocess.check_output(['git', '-C', str(chromium), 'show', f'HEAD:{expected}'])
            if (chromium / expected).read_bytes() != baseline:
                raise RuntimeError(f'Removed patch source differs from Chromium baseline: {patch}')
            os.utime(chromium / expected, None)
            print(f'Verified removed patch {patch} -> {expected}', flush=True)
            continue
        data = json.loads(info_path.read_text())
        targets = data.get('appliesTo')
        if (data.get('schemaVersion') != 1 or data.get('patchChecksum') != sha(repo / patch)
                or not isinstance(targets, list) or len(targets) != 1
                or targets[0].get('path') != expected
                or targets[0].get('checksum') != sha(chromium / expected)):
            raise RuntimeError(f'Patch application was not verified: {patch}')
        # A new timestamp forces the build graph to revisit the changed source.
        os.utime(chromium / expected, None)
        print(f'Verified {patch} -> {expected}', flush=True)


def prepare(repo, tools_repo, old, new, source_url):
    if run(repo, 'rev-parse', 'HEAD') != old:
        raise RuntimeError('Restored repository is not at the checkpoint commit')
    if run(repo, 'status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Restored Brave repository has tracked modifications')
    if run(tools_repo, 'rev-parse', 'HEAD') != new:
        raise RuntimeError('Tool checkout is not the requested upgrade commit')
    # Fetch on the GitHub runner: the sparse tools checkout may lack source blobs.
    subprocess.run(['git', '-C', str(repo), 'fetch', '--no-tags', '--depth=1', '--update-shallow',
                    source_url, new], check=True)
    patches = validate_diff(repo, old, new)
    subprocess.run(['git', '-C', str(repo), 'checkout', '--detach', new], check=True)
    if run(repo, 'rev-parse', 'HEAD') != new:
        raise RuntimeError('Upgrade checkout did not select the requested commit')
    return patches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--old', required=True)
    parser.add_argument('--new', required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    repo = workspace / 'src/brave'
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        raise ValueError('Invalid GitHub repository')
    source_url = f'https://github.com/{args.repository}.git'
    changed = prepare(repo, workspace / '.lite-tools', args.old, args.new, source_url)
    subprocess.run(['pnpm', 'run', 'apply_patches'], cwd=repo, check=True)
    validate_patches(repo, workspace / 'src', changed)
    print(f'Checkpoint source upgraded {args.old} -> {args.new}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Checkpoint source upgrade failed: {error}', file=sys.stderr)
        sys.exit(1)
