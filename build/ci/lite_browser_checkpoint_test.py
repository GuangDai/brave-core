#!/usr/bin/env python3
"""Test checkpoint provenance and the isolated browser-test overlay."""

import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import lite_browser_checkpoint as guard


class BrowserCheckpointTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'GITHUB_SHA': guard.SOURCE})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = Path(__file__).resolve().parents[2] / '.github/lite-testing/translation-tests.patch.b64'
        self.app = self.root / 'src/out/Static_arm64/Fixture.app/Contents'
        (self.app / 'MacOS').mkdir(parents=True)
        with (self.app / 'Info.plist').open('wb') as output:
            plistlib.dump({'CFBundleExecutable': 'Fixture'}, output)
        (self.app / 'MacOS/Fixture').write_bytes(b'app executable')
        self.brave = self.root / 'src/brave'
        for test_path in guard.TEST_BLOBS:
            (self.brave / Path(test_path).parent).mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', str(self.brave)], check=True)
        for test_path in guard.TEST_BLOBS:
            source = subprocess.check_output(['git', 'show', f'{guard.SOURCE}:{test_path}'],
                                             cwd=Path(__file__).resolve().parents[2])
            (self.brave / test_path).write_bytes(source)
        subprocess.run(['git', 'config', 'user.name', 'Fixture'], cwd=self.brave, check=True)
        subprocess.run(['git', 'config', 'user.email', 'fixture@example.invalid'], cwd=self.brave, check=True)
        subprocess.run(['git', 'add', *guard.TEST_BLOBS], cwd=self.brave, check=True)
        subprocess.run(['git', 'commit', '-qm', 'Fixture sources'], cwd=self.brave, check=True)
        self.manifest = {'identity': {'commit': guard.SOURCE, 'repository': 'example/project',
                                      'architecture': 'arm64'}, 'build_phase': 6,
                         'phase_complete': True}

    def test_overlay_is_pinned_idempotent_and_does_not_change_app(self):
        original = guard.app_digest(self.root)
        provenance = self.root / 'provenance.json'
        guard.prepare(self.root, self.manifest, guard.SOURCE, True, 'brave-lite',
                      self.patch, provenance)
        info = json.loads(provenance.read_text())
        self.assertEqual(info['test_overlay_sha256'], guard.OVERLAY_SHA256)
        self.assertEqual(info['app_binary_sha256'], original)
        guard.prepare_overlay(self.brave, guard.SOURCE, True, self.patch)
        self.assertEqual(guard.app_digest(self.root), original)

    def test_rejects_incomplete_or_wrong_checkpoint(self):
        for manifest in ({**self.manifest, 'phase_complete': False},
                         {**self.manifest, 'build_phase': 5},
                         {**self.manifest, 'checkpoint_kind': guard.KIND},
                         {**self.manifest, 'identity': {'commit': 'different'}}):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                guard.validate_checkpoint(manifest, guard.SOURCE, False, 'brave-lite')

    def test_resume_rejects_changed_overlay_or_app(self):
        provenance = self.root / 'provenance.json'
        guard.prepare(self.root, self.manifest, guard.SOURCE, True, 'brave-lite',
                      self.patch, provenance)
        saved = self.root / 'manifest.json'
        saved.write_text(json.dumps(self.manifest))
        guard.record(saved, provenance, 'checkpoint', 'time')
        manifest = json.loads(saved.read_text())
        with self.assertRaisesRegex(ValueError, 'provenance'):
            guard.validate_checkpoint(manifest, guard.SOURCE, False, 'brave-lite-verify')
        (self.app / 'MacOS/Fixture').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'executable differs'):
            guard.prepare(self.root, manifest, guard.SOURCE, True, 'brave-lite-verify',
                          self.patch, self.root / 'other.json')

    def test_wrong_patch_is_rejected_before_applying(self):
        wrong = self.root / 'wrong.patch'
        wrong.write_text('bm90IHRoZSB0ZXN0IHBhdGNo')
        with self.assertRaisesRegex(ValueError, 'overlay identity'):
            guard.prepare_overlay(self.brave, guard.SOURCE, True, wrong)

    def test_rejects_modified_or_partially_applied_sources(self):
        paths = list(guard.TEST_BLOBS)
        source = self.brave / paths[0]
        source.write_bytes(source.read_bytes() + b'\n// unexpected change\n')
        with self.assertRaisesRegex(ValueError, 'sources do not match'):
            guard.prepare_overlay(self.brave, guard.SOURCE, True, self.patch)
        subprocess.run(['git', 'checkout', '--', paths[0]], cwd=self.brave, check=True)
        guard.prepare_overlay(self.brave, guard.SOURCE, True, self.patch)
        subprocess.run(['git', 'checkout', '--', paths[0]], cwd=self.brave, check=True)
        with self.assertRaisesRegex(ValueError, 'sources do not match'):
            guard.prepare_overlay(self.brave, guard.SOURCE, True, self.patch)

    def test_disabled_overlay_rejects_staged_and_unstaged_changes(self):
        guard.prepare_overlay(self.brave, guard.SOURCE, False, self.patch)
        test_path = next(iter(guard.TEST_BLOBS))
        source = self.brave / test_path
        source.write_bytes(source.read_bytes() + b'\n// unexpected change\n')
        with self.assertRaises(subprocess.CalledProcessError):
            guard.prepare_overlay(self.brave, guard.SOURCE, False, self.patch)
        subprocess.run(['git', 'add', test_path], cwd=self.brave, check=True)
        with self.assertRaises(subprocess.CalledProcessError):
            guard.prepare_overlay(self.brave, guard.SOURCE, False, self.patch)


if __name__ == '__main__':
    unittest.main()
