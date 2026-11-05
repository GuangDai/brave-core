#!/usr/bin/env python3
"""Exercise separate read-only and writable compiler-cache backends."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import lite_cache_parts


class StageCacheTest(unittest.TestCase):
    def test_prior_hits_and_new_results_survive_separate_cache_artifacts(self):
        ccache = os.environ.get("LITE_CCACHE_TEST_BINARY") or shutil.which("ccache")
        compiler = shutil.which("clang") or shutil.which("cc")
        if not ccache or not compiler:
            self.skipTest("ccache and a C compiler are required")
        test_root = Path(__file__).resolve().parents[2] / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as temporary:
            root = Path(temporary)
            old, new = root / "old", root / "new"
            old.mkdir()
            new.mkdir()
            (root / "common.c").write_text("int common(void) { return 7; }\n")
            (root / "new.c").write_text("int newer(void) { return 8; }\n")
            env = {**os.environ, "CCACHE_DIR": str(root / "stats"),
                   "CCACHE_BASEDIR": str(root), "CCACHE_COMPILERCHECK": "content",
                   "CCACHE_REMOTE_ONLY": "true", "CCACHE_LOGFILE": str(root / "log")}

            def compile_one(source, output, backends):
                env["CCACHE_REMOTE_STORAGE"] = backends
                subprocess.run([ccache, compiler, "-c", source, "-o", output],
                               cwd=root, env=env, check=True, capture_output=True)
                return (root / "log").read_text()

            compile_one("common.c", "common.o", old.as_uri())
            backends = f"{old.as_uri()}|read-only {new.as_uri()}"
            log = compile_one("common.c", "common-again.o", backends)
            self.assertIn("Result: direct_cache_hit", log)
            compile_one("new.c", "new.o", backends)

            identity = {"repository": "example/project", "commit": "abc", "architecture": "arm64"}
            artifact = root / "brave-lite-shard-1-part-1-a1"
            lite_cache_parts.save(new, artifact, root / "state.json", identity,
                                  "1", 1, "checkpoint", "time")
            rescued = lite_cache_parts.verify(root, identity, "1", "1")
            self.assertTrue(rescued)
            before = (root / "log").read_text().count("Result: direct_cache_hit")
            log = compile_one("new.c", "new-resumed.o", rescued)
            self.assertGreater(log.count("Result: direct_cache_hit"), before)


if __name__ == "__main__":
    unittest.main()
