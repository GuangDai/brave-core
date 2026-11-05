#!/usr/bin/env python3
"""Test phase selection when resuming old and interrupted checkpoints."""

import unittest

import lite_stage_phase


class StagePhaseTest(unittest.TestCase):
    def test_unfinished_phase_is_resumed(self):
        manifest = lite_stage_phase.record_phase({}, 3, False)
        self.assertEqual(lite_stage_phase.next_phase(manifest, 1), 3)

    def test_finished_phase_advances_and_final_phase_is_capped(self):
        self.assertEqual(lite_stage_phase.next_phase(
            lite_stage_phase.record_phase({}, 3, True), 1), 4)
        self.assertEqual(lite_stage_phase.next_phase(
            lite_stage_phase.record_phase({}, 8, True), 1), 8)

    def test_legacy_metadata_and_invalid_values(self):
        self.assertEqual(lite_stage_phase.next_phase({}, 4), 4)
        for manifest in ({"build_phase": 9}, {"phase_complete": "true"}):
            with self.assertRaises(ValueError):
                lite_stage_phase.next_phase(manifest, 1)


if __name__ == "__main__":
    unittest.main()
