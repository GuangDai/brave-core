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

    def test_shared_bootstrap_begins_assembly_at_group_one(self):
        partial = lite_stage_phase.record_phase({}, 5, False, "bootstrap")
        with self.assertRaisesRegex(ValueError, "not complete"):
            lite_stage_phase.next_phase(partial, 5, shared_assembly=True)
        complete = lite_stage_phase.record_phase({}, 5, True, "bootstrap")
        self.assertEqual(lite_stage_phase.next_phase(complete, 5, shared_assembly=True), 1)
        self.assertEqual(lite_stage_phase.next_phase(complete, 5), 5)

    def test_shared_assembly_resumes_or_advances_its_group(self):
        partial = lite_stage_phase.record_phase({}, 2, False, "assembly")
        complete = lite_stage_phase.record_phase({}, 2, True, "assembly")
        self.assertEqual(lite_stage_phase.next_phase(partial, 1, shared_assembly=True), 2)
        self.assertEqual(lite_stage_phase.next_phase(complete, 1, shared_assembly=True), 3)


if __name__ == "__main__":
    unittest.main()
