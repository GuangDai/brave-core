#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import lite_checkpoint_upgrade as upgrade


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'config', 'user.name', 'Test')
        self.patch = next(iter(upgrade.PATCH_TARGETS))
        (self.repo / self.patch).parent.mkdir(parents=True)
        (self.repo / self.patch).write_text('before')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'initial')
        self.old = git(self.repo, 'rev-parse', 'HEAD')
        (self.repo / self.patch).write_text('after')
        git(self.repo, 'commit', '-qam', 'patch')
        self.new = git(self.repo, 'rev-parse', 'HEAD')

    def test_permitted_and_rejected_diff(self):
        self.assertEqual(upgrade.validate_diff(self.repo, self.old, self.new), [(self.patch, 'M')])
        (self.repo / 'DEPS').write_text('changed')
        git(self.repo, 'add', 'DEPS')
        git(self.repo, 'commit', '-qm', 'forbidden')
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            upgrade.validate_diff(self.repo, self.old, git(self.repo, 'rev-parse', 'HEAD'))

    def test_patch_metadata_and_source_integrity(self):
        target = upgrade.PATCH_TARGETS[self.patch]
        chromium = self.root / 'chromium'
        (chromium / target).parent.mkdir(parents=True)
        (chromium / target).write_text('patched source')
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        info = {'schemaVersion': 1, 'patchChecksum': digest(self.repo / self.patch),
                'appliesTo': [{'path': target, 'checksum': digest(chromium / target)}]}
        info_file = (self.repo / self.patch).with_suffix('.patchinfo')
        info_file.write_text(json.dumps(info))
        upgrade.validate_patches(self.repo, chromium, [(self.patch, 'M')])
        (chromium / target).write_text('unexpected source')
        with self.assertRaisesRegex(RuntimeError, 'not verified'):
            upgrade.validate_patches(self.repo, chromium, [(self.patch, 'M')])

    def test_removed_patch_requires_original_source_and_no_metadata(self):
        target = upgrade.PATCH_TARGETS[self.patch]
        chromium = self.root / 'chromium'
        chromium.mkdir()
        git(chromium, 'init', '-q')
        git(chromium, 'config', 'user.email', 'test@example.invalid')
        git(chromium, 'config', 'user.name', 'Test')
        (chromium / target).parent.mkdir(parents=True)
        (chromium / target).write_text('original')
        git(chromium, 'add', '.')
        git(chromium, 'commit', '-qm', 'original')
        upgrade.validate_patches(self.repo, chromium, [(self.patch, 'D')])
        (chromium / target).write_text('still patched')
        with self.assertRaisesRegex(RuntimeError, 'differs from Chromium baseline'):
            upgrade.validate_patches(self.repo, chromium, [(self.patch, 'D')])
        (chromium / target).write_text('original')
        (self.repo / self.patch).with_suffix('.patchinfo').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'metadata remains'):
            upgrade.validate_patches(self.repo, chromium, [(self.patch, 'D')])

    def test_prepare_uses_fixed_local_checkout_and_preserves_output(self):
        tools = self.root / 'tools'
        subprocess.run(['git', 'clone', '-q', '--depth', '1', self.repo.as_uri(), str(tools)], check=True)
        git(self.repo, 'checkout', '-q', '--detach', self.old)
        output = self.root / 'Static_arm64' / 'object.o'
        output.parent.mkdir()
        output.write_bytes(b'previous compilation')
        self.assertEqual(upgrade.prepare(self.repo, tools, self.old, self.new, tools.as_uri()), [(self.patch, 'M')])
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), self.new)
        self.assertEqual(output.read_bytes(), b'previous compilation')
        with self.assertRaisesRegex(RuntimeError, 'checkpoint commit'):
            upgrade.prepare(self.repo, tools, self.old, self.new, tools.as_uri())


if __name__ == '__main__':
    unittest.main()
