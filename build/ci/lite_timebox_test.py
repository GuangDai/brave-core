#!/usr/bin/env python3
"""Tests for checkpoint handoff and failed command reporting."""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import tempfile
import subprocess

import lite_timebox


class TimeboxTest(unittest.TestCase):
    def test_success_and_compiler_failure_are_distinct(self):
        workspace = Path.cwd()
        self.assertEqual(
            lite_timebox.run_build([sys.executable, "-c", "pass"], workspace,
                                   time.time() + 30, 0),
            ("complete", "", 0),
        )
        self.assertEqual(
            lite_timebox.run_build([sys.executable, "-c", "raise SystemExit(5)"],
                                   workspace, time.time() + 30, 0),
            ("failed", "", 5),
        )

    def test_time_limit_stops_a_running_process(self):
        result = lite_timebox.run_build(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            Path.cwd(), time.time() + 0.2, 0,
        )
        self.assertEqual(result, ("checkpoint", "time", 0))

    def test_low_disk_does_not_start_the_command(self):
        result = lite_timebox.run_build(
            [sys.executable, "-c", "raise SystemExit(9)"],
            Path.cwd(), time.time() + 30, 2 ** 70,
        )
        self.assertEqual(result, ("checkpoint", "disk", 0))

    def test_large_cache_stops_the_compiler(self):
        test_root = Path(__file__).resolve().parents[2] / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as name:
            cache = Path(name)
            (cache / "object").write_bytes(b"1234")
            with patch("lite_timebox.subprocess.Popen") as popen, \
                    patch("lite_timebox.stop_group") as stop:
                popen.return_value.wait.side_effect = subprocess.TimeoutExpired("build", 10)
                result = lite_timebox.run_build(["build"], Path.cwd(),
                                                time.time() + 30, 0, cache, 4)
                stop.assert_called_once_with(popen.return_value)
                self.assertEqual(result, ("checkpoint", "cache", 0))


if __name__ == "__main__":
    unittest.main()
