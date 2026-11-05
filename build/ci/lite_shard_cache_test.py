#!/usr/bin/env python3
"""Test shard completeness, identity and corruption detection."""

from pathlib import Path
import tempfile
import unittest

import lite_shard_cache


class ShardCacheTest(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[2] / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {"repository": "example/project", "commit": "abc"}
        for shard, target in lite_shard_cache.TARGETS.items():
            path = self.root / f"brave-lite-shard-{shard}-a1"
            cache = path / "cache" / "aa"
            cache.mkdir(parents=True)
            (cache / "entry").write_text(f"compiled object {shard}")
            lite_shard_cache.save(path, self.identity, shard, target, "checkpoint", "time")

    def test_all_shards_are_validated(self):
        backends = lite_shard_cache.verify_set(self.root, self.identity, "1")
        self.assertEqual(backends.count("|read-only"), 5)

    def test_corruption_and_other_commit_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "identity"):
            lite_shard_cache.verify_set(self.root, {"commit": "other"}, "1")
        entry = self.root / "brave-lite-shard-2-a1" / "cache" / "aa" / "entry"
        entry.write_text("modified")
        with self.assertRaisesRegex(RuntimeError, "failed verification"):
            lite_shard_cache.verify_set(self.root, self.identity, "1")

    def test_symlink_is_rejected(self):
        entry = self.root / "brave-lite-shard-1-a1" / "cache" / "link"
        entry.symlink_to("aa/entry")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            lite_shard_cache.verify_set(self.root, self.identity, "1")


if __name__ == "__main__":
    unittest.main()
