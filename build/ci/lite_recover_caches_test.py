#!/usr/bin/env python3
"""Verify downloaded cache recovery without building the browser."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import lite_recover_caches as recovery
from lite_shard_cache import TARGETS, entries


class CacheRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        (self.workspace / "src/out/Static").mkdir(parents=True)
        self.artifacts = self.root / "downloaded"
        self.artifacts.mkdir()

    def artifact(self, name, shard, part=None, run="123"):
        path = self.artifacts / f"run-{run}" / name
        cache = path / "cache"
        (cache / "aa").mkdir(parents=True)
        (cache / "aa" / "entry").write_bytes(b"cache data")
        manifest = {"version": 1, "identity": {"repository": "GuangDai/brave-core", "architecture": "arm64"},
                    "shard": shard, "target": TARGETS[shard], "outcome": "failed", "files": entries(cache)}
        if part is not None:
            manifest["part"] = part
        (path / "manifest.json").write_text(json.dumps(manifest))
        return path

    def test_multiple_runs_stages_and_parts_are_verified_in_priority_order(self):
        first = self.artifact("brave-lite-shard-1-part-1-a1", "1", 1, "100")
        later = self.artifact("brave-lite-stage-2-shard-5-part-2-a1", "5", 2, "101")
        before = self.artifact("brave-lite-stage-2-shard-5-part-1-a1", "5", 1, "101")
        legacy = self.artifact("brave-lite-shard-2-a1", "2", run="100")
        result = recovery.verified_backends([self.artifacts], "GuangDai/brave-core")
        self.assertEqual(result, [later / "cache", before / "cache", legacy / "cache", first / "cache"])
        values = recovery.settings(result, [self.artifacts], self.workspace, self.root / "new cache")
        self.assertEqual(values["CCACHE_REMOTE_ONLY"], "true")
        self.assertEqual(values["CCACHE_NOREADONLY"], "true")
        self.assertTrue(values["CCACHE_REMOTE_STORAGE"].endswith("/new%20cache/remote"))
        self.assertEqual(values["CCACHE_REMOTE_STORAGE"].count("|read-only"), 4)

    def test_modified_or_wrong_identity_artifact_rejects_all(self):
        path = self.artifact("brave-lite-shard-1-part-1-a1", "1", 1)
        (path / "cache/aa/entry").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "differ"):
            recovery.verified_backends([self.artifacts], "GuangDai/brave-core")
        with self.assertRaisesRegex(ValueError, "identity"):
            recovery.verified_backends([self.artifacts], "other/repo")
        command = [sys.executable, str(Path(recovery.__file__)), "--check-only",
                   "--root", str(self.artifacts), "--repository", "GuangDai/brave-core"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_wrong_architecture_is_rejected(self):
        path = self.artifact("brave-lite-shard-1-part-1-a1", "1", 1)
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["identity"]["architecture"] = "x86_64"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "identity"):
            recovery.verified_backends([self.artifacts], "GuangDai/brave-core")

    def test_non_integer_file_size_is_rejected(self):
        path = self.artifact("brave-lite-shard-1-part-1-a1", "1", 1)
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["size"] = True
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "file list"):
            recovery.verified_backends([self.artifacts], "GuangDai/brave-core")

    def test_invalid_attempt_and_outcome_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "attempt"):
            recovery.artifact_info("brave-lite-shard-1-part-1-a0")
        path = self.artifact("brave-lite-shard-1-part-1-a1", "1", 1)
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["outcome"] = []
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "identity"):
            recovery.verified_backends([self.artifacts], "GuangDai/brave-core")

    def test_symlinks_are_rejected(self):
        path = self.artifact("brave-lite-shard-1-part-1-a1", "1", 1)
        (path / "cache/aa/link").symlink_to("entry")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            recovery.verified_backends([self.artifacts], "GuangDai/brave-core")

    def test_writable_cache_cannot_overlap_backups(self):
        path = self.artifact("brave-lite-shard-1-part-1-a1", "1", 1)
        backends = recovery.verified_backends([self.artifacts], "GuangDai/brave-core")
        with self.assertRaisesRegex(ValueError, "separate"):
            recovery.settings(backends, [self.artifacts], self.workspace, path / "new")
        with self.assertRaisesRegex(ValueError, "separate"):
            recovery.settings(backends, [self.artifacts], self.workspace, self.root)
        other = self.artifact("brave-lite-shard-2-part-1-a1", "2", 1)
        with self.assertRaisesRegex(ValueError, "separate"):
            recovery.settings(backends, [path], self.workspace, other)

    def test_empty_artifact_does_not_discard_other_parts(self):
        path = self.artifact("brave-lite-shard-1-part-1-a1", "1", 1)
        empty = self.artifacts / "run-123/brave-lite-shard-1-part-2-a1"
        empty.mkdir()
        (empty / "manifest.json").write_text(json.dumps({
            "version": 1, "identity": {"repository": "GuangDai/brave-core", "architecture": "arm64"},
            "shard": "1", "part": 2, "target": TARGETS["1"], "outcome": "checkpoint", "files": []}))
        self.assertEqual(recovery.verified_backends([self.artifacts], "GuangDai/brave-core"), [path / "cache"])

    def test_real_ccache_reuses_readonly_and_saves_new_result(self):
        ccache = os.environ.get("LITE_CCACHE_TEST_BINARY") or shutil.which("ccache")
        compiler = shutil.which("clang") or shutil.which("cc")
        if not ccache or not compiler:
            self.skipTest("ccache and a C compiler are required")
        build = self.workspace / "src/out/Static"
        (self.workspace / "src/old.c").write_text("int old(void) { return 7; }\n")
        (self.workspace / "src/new.c").write_text("int newer(void) { return 8; }\n")
        cache = self.artifacts / "run-123/brave-lite-shard-1-part-1-a1/cache"
        cache.mkdir(parents=True)
        env = {key: value for key, value in os.environ.items() if not key.startswith("CCACHE_")}
        env.update({"CCACHE_BASEDIR": str(self.workspace), "CCACHE_COMPILERCHECK": "content",
                    "CCACHE_REMOTE_ONLY": "true", "CCACHE_REMOTE_STORAGE": cache.as_uri(),
                    "CCACHE_DIR": str(self.root / "seed-stats"), "CCACHE_LOGFILE": str(self.root / "log")})
        subprocess.run([ccache, compiler, "-c", "../../old.c", "-o", "old.o"],
                       cwd=build, env=env, check=True, capture_output=True)
        manifest = {"version": 1, "identity": {"repository": "GuangDai/brave-core", "architecture": "arm64"},
                    "shard": "1", "part": 1, "target": TARGETS["1"], "outcome": "checkpoint",
                    "files": entries(cache)}
        (cache.parent / "manifest.json").write_text(json.dumps(manifest))
        original = entries(cache)
        backends = recovery.verified_backends([self.artifacts], "GuangDai/brave-core")
        env.update(recovery.settings(backends, [self.artifacts], self.workspace, self.root / "new-cache"))
        subprocess.run([ccache, compiler, "-c", "../../old.c", "-o", "old-again.o"],
                       cwd=build, env=env, check=True, capture_output=True)
        self.assertIn("Result: direct_cache_hit", (self.root / "log").read_text())
        subprocess.run([ccache, compiler, "-c", "../../new.c", "-o", "new.o"],
                       cwd=build, env=env, check=True, capture_output=True)
        self.assertTrue(entries(self.root / "new-cache/remote"))
        self.assertEqual(entries(cache), original)


if __name__ == "__main__":
    unittest.main()
