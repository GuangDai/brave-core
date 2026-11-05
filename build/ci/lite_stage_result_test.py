#!/usr/bin/env python3
"""Exercise continuation and failure selection across cache parts."""

import unittest

import lite_stage_result


class StageResultTest(unittest.TestCase):
    def test_finished_target_moves_to_the_next_phase(self):
        result = lite_stage_result.summarize("v8:v8", [{"outcome": "complete"}])
        self.assertEqual(result, {"compile_outcome": "complete", "outcome": "checkpoint", "reason": "next"})

    def test_interrupted_final_part_is_resumed(self):
        result = lite_stage_result.summarize("browser", [
            {"outcome": "checkpoint", "reason": "cache"},
            {"outcome": "checkpoint", "reason": "time"}, {}, {}])
        self.assertEqual(result["outcome"], "checkpoint")
        self.assertEqual(result["reason"], "time")

    def test_part_failure_wins_over_an_earlier_checkpoint(self):
        result = lite_stage_result.summarize("browser", [
            {"outcome": "checkpoint", "reason": "time"}, {"status": "failure"}, {}, {}])
        self.assertEqual(result["compile_outcome"], "failed")
        self.assertEqual(result["outcome"], "failed")

    def test_finished_browser_is_complete(self):
        result = lite_stage_result.summarize("", [{"outcome": "complete"}])
        self.assertEqual(result["outcome"], "complete")
        with self.assertRaises(ValueError):
            lite_stage_result.summarize("", [{}])


if __name__ == "__main__":
    unittest.main()
