#!/usr/bin/env python3
"""Check source validation and incremental output restoration."""

import os
from pathlib import Path
import tempfile
import unittest

import lite_thin_checkpoint


class ThinCheckpointTest(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[2] / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / "original"
        self.fresh = self.root / "fresh"
        self.baseline = self.root / "baseline.json"
        self.checkpoint = self.root / "checkpoint"
        self.identity = {"repository": "example/project", "commit": "abc",
                         "workspace": "/workspace", "architecture": "arm64",
                         "image_os": "macos26", "image_version": "one",
                         "macos_version": "26.6.2", "xcode_version": "26.6",
                         "sdk_version": "26.5"}
        for workspace in (self.original, self.fresh):
            (workspace / "src" / "brave").mkdir(parents=True)
            (workspace / "src" / "brave" / "fixed.h").write_text("fixed source")
            (workspace / "src" / "brave" / "changed.cc").write_text("original source")
            (workspace / "src" / "brave" / "alias").symlink_to("fixed.h")
        old_time = 1_600_000_000_123_456_789
        os.utime(self.original / "src" / "brave" / "fixed.h", ns=(old_time, old_time))
        lite_thin_checkpoint.capture_baseline(self.original, self.baseline)

    def create_checkpoint(self):
        (self.original / "src" / "brave" / "changed.cc").write_text("generated source")
        (self.original / "src" / "brave" / "new.h").write_text("new source")
        output = self.original / "src" / "out" / "Static_arm64"
        output.mkdir(parents=True)
        (output / "object.o").write_bytes(b"compiled-object")
        (output / "executable").write_text("#!/bin/sh\n")
        (output / "executable").chmod(0o755)
        (output / "alias").symlink_to("executable")
        lite_thin_checkpoint.save(self.original, self.baseline, self.root / "save-stage",
                                  self.checkpoint, self.identity, 100_000)

    def test_output_changes_and_source_timestamps_survive(self):
        self.create_checkpoint()
        lite_thin_checkpoint.restore(self.fresh, self.checkpoint, self.root / "restore-stage",
                                     self.identity)
        base = self.fresh / "src" / "brave"
        output = self.fresh / "src" / "out" / "Static_arm64"
        self.assertEqual((base / "changed.cc").read_text(), "generated source")
        self.assertEqual((base / "new.h").read_text(), "new source")
        self.assertEqual((base / "fixed.h").stat().st_mtime_ns, 1_600_000_000_123_456_789)
        self.assertEqual(os.readlink(base / "alias"), "fixed.h")
        self.assertEqual((output / "object.o").read_bytes(), b"compiled-object")
        self.assertEqual((output / "executable").stat().st_mode & 0o777, 0o755)
        self.assertEqual(os.readlink(output / "alias"), "executable")

    def test_incompatible_source_and_existing_output_are_preserved(self):
        self.create_checkpoint()
        fixed = self.fresh / "src" / "brave" / "fixed.h"
        fixed.write_text("different contents")
        with self.assertRaisesRegex(RuntimeError, "differs from baseline"):
            lite_thin_checkpoint.restore(self.fresh, self.checkpoint, self.root / "restore-stage",
                                         self.identity)
        self.assertEqual(fixed.read_text(), "different contents")
        self.assertFalse((self.fresh / "src" / "out").exists())
        (self.fresh / "src" / "out").mkdir()
        with self.assertRaisesRegex(RuntimeError, "without build output"):
            lite_thin_checkpoint.restore(self.fresh, self.checkpoint, self.root / "other-stage",
                                         self.identity)


if __name__ == "__main__":
    unittest.main()
