#!/usr/bin/env python3
"""Test safe reuse of browser-verification compiler cache parts."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import lite_browser_test_cache_restore as restore
from lite_shard_cache import TARGETS, entries


class BrowserTestCacheRestoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache_root = self.root / 'lite-browser-verify-cache'
        self.cache_root.mkdir()
        self.identity = {'repository': 'example/project', 'commit': 'a' * 40,
                         'workspace': '/workspace', 'architecture': 'arm64',
                         'image_os': 'macos26', 'image_version': 'first',
                         'macos_version': '26.6.2', 'xcode_version': '26.6',
                         'sdk_version': '26.5'}
        self.provenance = {'test_repository': 'example/project', 'test_architecture': 'arm64',
                           'test_source_commit': 'a' * 40, 'test_overlay': False,
                           'test_overlay_commit': '', 'test_overlay_sha256': '',
                           'app_binary_sha256': 'b' * 64, 'verification_workflow_commit': 'c' * 40}

    def artifact(self, part, content=b'compiled result'):
        name = f'{restore.PREFIX}{part}-a1'
        path = self.cache_root / name
        cache = path / 'cache' / 'ab'
        cache.mkdir(parents=True)
        (cache / 'result').write_bytes(content)
        manifest = {'version': 1, 'identity': self.identity, 'shard': '5',
                    'target': TARGETS['5'], 'part': part, 'outcome': 'checkpoint',
                    'actual_build_target': 'brave_browser_tests',
                    'cache_purpose': 'browser-verification',
                    'verification_provenance': dict(self.provenance), 'files': entries(path / 'cache')}
        (path / 'manifest.json').write_text(json.dumps(manifest))
        return name, path, manifest

    def inventory(self, parts=(1, 2)):
        items = [{'id': part, 'name': f'{restore.PREFIX}{part}-a1', 'expired': False,
                  'size_in_bytes': 100, 'workflow_run': {'id': 42}} for part in parts]
        return [{'total_count': len(items), 'artifacts': items}]

    def test_preflight_checks_input_budget_and_inventory(self):
        pages = self.inventory()
        minimum = 32 * 1024 ** 3 + 400
        self.assertEqual(restore.preflight('42', '1', 0, 1, minimum, pages),
                         [f'{restore.PREFIX}2-a1', f'{restore.PREFIX}1-a1'])
        self.assertEqual(restore.preflight('42', '1', 0, 205 * 60, minimum, pages), [])
        self.assertEqual(restore.preflight('42', '1', 0, 1, minimum - 1, pages), [])
        self.assertEqual(restore.preflight('42', '1', 0, 1, minimum, self.inventory(())), [])
        with self.assertRaises(ValueError):
            restore.preflight('42', '0', 0, 1, minimum, pages)
        with self.assertRaises(ValueError):
            restore.preflight('42', '1', 0, 1, minimum, [{'total_count': 3, 'artifacts': pages[0]['artifacts']}])
        pages[0]['artifacts'][0]['workflow_run']['id'] = 99
        with self.assertRaises(ValueError):
            restore.preflight('42', '1', 0, 1, minimum, pages)
        pages = self.inventory()
        pages[0]['artifacts'][0]['workflow_run'] = None
        with self.assertRaises(ValueError):
            restore.preflight('42', '1', 0, 1, minimum, pages)
        pages = self.inventory()
        pages[0]['artifacts'][0]['id'] = None
        with self.assertRaises(ValueError):
            restore.preflight('42', '1', 0, 1, minimum, pages)

    def test_valid_parts_are_readonly_and_newest_first(self):
        first, first_path, _ = self.artifact(1)
        second, second_path, _ = self.artifact(2, b'newer')
        result = restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [first, second])
        self.assertEqual(result, [(second_path / 'cache').as_uri() + '|read-only',
                                  (first_path / 'cache').as_uri() + '|read-only'])

    def test_missing_or_unexpected_part_is_rejected(self):
        first, _, _ = self.artifact(1)
        self.artifact(2)
        with self.assertRaisesRegex(ValueError, 'differ from inventory'):
            restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [first])
        with self.assertRaisesRegex(ValueError, 'differ from inventory'):
            restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [first, f'{restore.PREFIX}3-a1'])

    def test_wrong_identity_target_or_purpose_is_rejected(self):
        name, path, manifest = self.artifact(1)
        for field, value in (('actual_build_target', 'brave'), ('cache_purpose', 'app'),
                             ('shard', '4'), ('part', 2)):
            altered = {**manifest, field: value}
            (path / 'manifest.json').write_text(json.dumps(altered))
            with self.subTest(field=field), self.assertRaises(ValueError):
                restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [name])
        altered = {**manifest, 'identity': {**self.identity, 'commit': 'b' * 40}}
        (path / 'manifest.json').write_text(json.dumps(altered))
        with self.assertRaises(ValueError):
            restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [name])

    def test_cache_provenance_fields_are_strictly_validated(self):
        name, path, manifest = self.artifact(1)
        for field, value in (('test_repository', 'other/project'), ('test_architecture', 'x86_64'),
                             ('test_source_commit', 'd' * 40), ('test_overlay', 0),
                             ('test_overlay_commit', 'd' * 40), ('test_overlay_sha256', 'e' * 64),
                             ('app_binary_sha256', 'not-a-sha'), ('verification_workflow_commit', 'bad')):
            altered = {**manifest, 'verification_provenance': {**self.provenance, field: value}}
            (path / 'manifest.json').write_text(json.dumps(altered))
            with self.subTest(field=field), self.assertRaises(ValueError):
                restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [name])
        for value in (None, [], 'invalid'):
            (path / 'manifest.json').write_text(json.dumps({**manifest, 'verification_provenance': value}))
            with self.subTest(value=value), self.assertRaises(ValueError):
                restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [name])

    def test_cache_must_match_current_overlay_and_application(self):
        name, path, manifest = self.artifact(1)
        source = restore.SOURCE
        current = {**self.identity, 'commit': source}
        plain = {**self.provenance, 'test_source_commit': source}
        overlay = {**plain, 'test_overlay': True, 'test_overlay_commit': restore.OVERLAY_COMMIT,
                   'test_overlay_sha256': restore.OVERLAY_SHA256}
        manifest['identity'] = current
        manifest['verification_provenance'] = overlay
        (path / 'manifest.json').write_text(json.dumps(manifest))
        self.assertEqual(len(restore.verified_backends(self.cache_root, current, overlay, '42', '1', [name])), 1)
        with self.assertRaisesRegex(ValueError, 'overlay or application differs'):
            restore.verified_backends(self.cache_root, current, plain, '42', '1', [name])
        with self.assertRaisesRegex(ValueError, 'overlay or application differs'):
            restore.verified_backends(self.cache_root, current, {**overlay, 'app_binary_sha256': 'd' * 64},
                                      '42', '1', [name])
        manifest['verification_provenance'] = {**overlay, 'test_overlay_commit': 'd' * 40}
        (path / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'overlay provenance differs'):
            restore.verified_backends(self.cache_root, current, overlay, '42', '1', [name])

    def test_different_workflow_commit_is_allowed_if_app_and_overlay_match(self):
        name, path, manifest = self.artifact(1)
        manifest['verification_provenance']['verification_workflow_commit'] = 'd' * 40
        (path / 'manifest.json').write_text(json.dumps(manifest))
        self.assertEqual(len(restore.verified_backends(self.cache_root, self.identity,
                                                       self.provenance, '42', '1', [name])), 1)

    def test_modified_file_symlink_and_invalid_file_metadata_are_rejected(self):
        name, path, manifest = self.artifact(1)
        target = path / 'cache/ab/result'
        target.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'contents differ'):
            restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [name])
        target.write_bytes(b'compiled result')
        manifest['files'][0]['size'] = True
        (path / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Invalid cache file list'):
            restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [name])
        manifest['files'][0]['size'] = len(b'compiled result')
        (path / 'manifest.json').write_text(json.dumps(manifest))
        (path / 'cache/ab/link').symlink_to('result')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [name])

    def test_broken_cache_symlink_is_rejected_even_for_empty_part(self):
        name = f'{restore.PREFIX}1-a1'
        path = self.cache_root / name
        path.mkdir()
        (path / 'manifest.json').write_text(json.dumps({
            'version': 1, 'identity': self.identity, 'shard': '5', 'target': TARGETS['5'],
            'part': 1, 'outcome': 'checkpoint', 'actual_build_target': 'brave_browser_tests',
            'cache_purpose': 'browser-verification', 'files': []}))
        (path / 'cache').symlink_to('missing')
        with self.assertRaisesRegex(ValueError, 'Invalid cache artifact'):
            restore.verified_backends(self.cache_root, self.identity, self.provenance, '42', '1', [name])

    def test_corrupt_later_part_never_updates_environment(self):
        first, path, _ = self.artifact(1)
        second, _, _ = self.artifact(2)
        (path / 'cache/ab/result').write_bytes(b'corrupt')
        env_path = self.root / 'github-env'
        env_path.write_text('EXISTING=value\n')
        provenance_dir = self.root / 'browser-verification'
        provenance_dir.mkdir()
        (provenance_dir / 'provenance.json').write_text(json.dumps(self.provenance))
        environment = {'VERIFY_CACHE_RUN': '42', 'VERIFY_CACHE_ATTEMPT': '1',
                       'GITHUB_REPOSITORY': 'example/project', 'LITE_SOURCE_COMMIT': 'a' * 40,
                       'GITHUB_WORKSPACE': str(self.root), 'RUNNER_TEMP': str(self.root),
                       'EXPECTED_CACHE_NAMES': json.dumps([first, second]), 'GITHUB_ENV': str(env_path),
                       'CCACHE_REMOTE_STORAGE': 'file:///old|read-only'}
        with patch.dict(os.environ, environment, clear=True), patch.object(sys, 'argv', ['restore', 'verify']), \
             patch.object(restore, 'identity', return_value=self.identity):
            with self.assertRaises(ValueError):
                restore.main()
        self.assertEqual(env_path.read_text(), 'EXISTING=value\n')


if __name__ == '__main__':
    unittest.main()
