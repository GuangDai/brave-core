#!/usr/bin/env python3
"""Test incremental and partial cache recovery."""

import os
from pathlib import Path
import shutil
import tempfile
import unittest

import lite_cache_parts


class CachePartsTest(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[2] / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "source"
        (self.cache / "aa").mkdir(parents=True)
        self.state = self.root / "state.json"
        self.identity = {"repository": "example/project", "commit": "abc",
                         "architecture": "arm64"}

    def part(self, number):
        return self.root / f"brave-lite-shard-1-part-{number}-a1"

    def test_incremental_parts_restore_even_when_one_is_missing(self):
        (self.cache / "aa" / "one").write_bytes(b"first")
        lite_cache_parts.save(self.cache, self.part(1), self.state, self.identity,
                              "1", 1, "checkpoint", "cache")
        self.assertEqual((self.cache / "aa" / "one").stat().st_ino,
                         (self.part(1) / "cache" / "aa" / "one").stat().st_ino)
        (self.cache / "aa" / "two").write_bytes(b"second")
        replacement = self.cache / "replacement"
        replacement.write_bytes(b"updated")
        os.replace(replacement, self.cache / "aa" / "one")
        lite_cache_parts.save(self.cache, self.part(2), self.state, self.identity,
                              "1", 2, "failed", "")
        result = lite_cache_parts.verify(self.root, self.identity, "1", "1")
        self.assertEqual(result.count("|read-only"), 2)
        self.assertLess(result.index("part-2"), result.index("part-1"))

        partial = self.root / "partial"
        partial.mkdir()
        shutil.copytree(self.part(2), partial / self.part(2).name)
        self.assertEqual(lite_cache_parts.verify(partial, self.identity, "1", "1")
                         .count("|read-only"), 1)

    def test_modified_part_is_rejected(self):
        (self.cache / "aa" / "one").write_bytes(b"first")
        lite_cache_parts.save(self.cache, self.part(1), self.state, self.identity,
                              "1", 1, "checkpoint", "time")
        (self.part(1) / "cache" / "aa" / "one").write_bytes(b"broken")
        with self.assertRaisesRegex(RuntimeError, "failed verification"):
            lite_cache_parts.verify(self.root, self.identity, "1", "1")


if __name__ == "__main__":
    unittest.main()
