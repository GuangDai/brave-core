#!/usr/bin/env python3
"""Tests for checkpoint handoff and failed command reporting."""

from pathlib import Path
import sys
import time
import unittest

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


if __name__ == "__main__":
    unittest.main()
