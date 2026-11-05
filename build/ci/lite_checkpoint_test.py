#!/usr/bin/env python3
"""Tests for checkpoint completeness, integrity and Unix file metadata."""

import json
import os
from pathlib import Path
import tempfile
import unittest

import lite_checkpoint


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[2] / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.saved = self.root / "checkpoint"
        self.restored = self.root / "restored"
        self.identity = {"repository": "example/project", "commit": "abc"}

    def test_round_trip_preserves_files_permissions_and_symlinks(self):
        (self.work / "object.o").write_bytes(os.urandom(250_000))
        binary = self.work / "executable"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        (self.work / "alias").symlink_to("executable")
        (self.work / ".lite-tools").mkdir()
        (self.work / ".lite-tools" / "excluded").write_text("temporary")

        lite_checkpoint.save(self.work, self.saved, self.identity, 100_000)
        manifest = json.loads((self.saved / "manifest.json").read_text())
        self.assertGreater(len(manifest["volumes"]), 1)
        lite_checkpoint.restore(self.restored, self.saved, self.identity)

        self.assertEqual((self.work / "object.o").read_bytes(),
                         (self.restored / "object.o").read_bytes())
        self.assertEqual((self.restored / "executable").stat().st_mode & 0o777,
                         0o755)
        self.assertEqual(os.readlink(self.restored / "alias"), "executable")
        self.assertFalse((self.restored / ".lite-tools").exists())

    def test_corrupt_or_missing_part_is_rejected_before_extraction(self):
        (self.work / "file").write_bytes(os.urandom(10_000))
        lite_checkpoint.save(self.work, self.saved, self.identity, 100_000)
        part = self.saved / "part-aa"
        original = part.read_bytes()
        part.write_bytes(b"X" + original[1:])

        with self.assertRaisesRegex(RuntimeError, "failed verification"):
            lite_checkpoint.restore(self.restored, self.saved, self.identity)
        self.assertEqual(list(self.restored.iterdir()), [])

    def test_different_build_identity_is_rejected(self):
        (self.work / "file").write_text("content")
        lite_checkpoint.save(self.work, self.saved, self.identity, 100_000)
        with self.assertRaisesRegex(RuntimeError, "toolchain differs"):
            lite_checkpoint.restore(self.restored, self.saved, {"commit": "other"})
        self.assertEqual(list(self.restored.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
