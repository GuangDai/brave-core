#!/usr/bin/env python3
"""Test a real Siso/ccache invocation against a tiny source override."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class SisoCcacheTest(unittest.TestCase):
    def test_ccache_preserves_brave_source_redirection(self):
        siso = os.environ.get("LITE_SISO_TEST_BINARY")
        ccache = os.environ.get("LITE_CCACHE_TEST_BINARY")
        clang = shutil.which("clang")
        compiler = clang or shutil.which("cc")
        if not siso or not ccache or not compiler:
            self.skipTest("Set LITE_SISO_TEST_BINARY and LITE_CCACHE_TEST_BINARY")
        repository = Path(__file__).resolve().parents[2]
        test_root = repository / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as temporary:
            root = Path(temporary)
            src = root / "src"
            config = src / "build" / "config" / "siso"
            build = src / "out" / "Static"
            source = src / "base" / "example.cc"
            override = src / "brave" / "chromium_src" / "base" / "example.cc"
            fake_compiler = src / "third_party" / "llvm-build" / "Release+Asserts" / "bin" / "clang"
            for directory in (config, build, source.parent, override.parent, fake_compiler.parent):
                directory.mkdir(parents=True, exist_ok=True)
            (src / ".gn").write_text("")
            source.write_text('#error "the Brave override was skipped"\n')
            override.write_text('int brave_override(void) { return 42; }\n')
            fake_compiler.symlink_to(compiler)
            shutil.copyfile(repository / "build/config/siso/brave_siso_config.star",
                            config / "brave_siso_config.star")
            (config / "platform.star").write_text(
                'load("@builtin//struct.star", "module")\n'
                'platform = module("platform", python_bin="python3", remote_python_bin="python3")\n')
            (config / "tsc.star").write_text(
                'load("@builtin//struct.star", "module")\ntsc = module("tsc")\n')
            (config / "main.star").write_text('''\
load("@builtin//encoding.star", "json")
load("@builtin//struct.star", "module")
load("./brave_siso_config.star", "brave_siso_config")
def init(ctx):
    step_config = {"rules": [], "platforms": {}, "input_deps": {}}
    filegroups = {"third_party/llvm-build/Release+Asserts/stub": {"type": "glob", "includes": []}}
    handlers = {}
    brave_siso_config.configure(ctx, step_config, filegroups, handlers)
    return module("config", step_config=json.encode(step_config), filegroups=filegroups, handlers=handlers)
''')
            (build / "build.ninja").write_text('''\
rule cxx
  command = ccache ../../third_party/llvm-build/Release+Asserts/bin/clang -c ../../base/example.cc -o example.o
build example.o: cxx ../../base/example.cc
''')
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "ccache").symlink_to(Path(ccache).resolve())
            env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                   "CCACHE_DIR": str(root / "ccache-stats"),
                   "CCACHE_BASEDIR": str(src), "CCACHE_COMPILERCHECK": "content",
                   "CCACHE_REMOTE_ONLY": "true",
                   "CCACHE_REMOTE_STORAGE": (root / "ccache-results").as_uri()}
            if not clang:
                env["CCACHE_COMPILERTYPE"] = "gcc"
            command = [siso, "ninja", "-C", "out/Static", "-offline",
                       "-cache_dir", str(root / "siso-cache"), "example.o"]
            completed = subprocess.run(command, cwd=src, env=env, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertTrue((build / "example.o").is_file())
            self.assertTrue(any((root / "ccache-results").rglob("*")))


if __name__ == "__main__":
    unittest.main()
