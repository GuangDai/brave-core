#!/usr/bin/env python3
"""Test checkpoint provenance and the isolated translation-test overlay."""

import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest

import lite_browser_checkpoint as guard


class BrowserCheckpointTest(unittest.TestCase):
    def setUp(self):
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
        (self.brave / Path(guard.TEST_PATH).parent).mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.brave)], check=True)
        source = subprocess.check_output(['git', 'show', f'{guard.SOURCE}:{guard.TEST_PATH}'],
                                         cwd=Path(__file__).resolve().parents[2])
        (self.brave / guard.TEST_PATH).write_bytes(source)
        self.manifest = {'identity': {'commit': guard.SOURCE}, 'build_phase': 6,
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


if __name__ == '__main__':
    unittest.main()
