#!/usr/bin/env python3
"""Check optional cache budget and artifact selection."""

import unittest

from lite_rescue_preflight import eligible


class RescuePreflightTest(unittest.TestCase):
    def setUp(self):
        self.env = {'RESCUE_RUN': '123', 'RESCUE_SHARD': '1', 'RESCUE_ATTEMPT': '2',
                    'RESCUE_KIND': 'stage', 'RESCUE_STAGE': '4', 'LITE_JOB_STARTED': '1000'}
        self.items = [{'artifacts': [
            {'name': 'brave-lite-stage-4-shard-1-part-1-a2', 'expired': False, 'size_in_bytes': 500},
            {'name': 'brave-lite-stage-4-shard-1-part-2-a2', 'expired': False, 'size_in_bytes': 300},
            {'name': 'brave-lite-stage-4-shard-1-part-3-a2', 'expired': True, 'size_in_bytes': 900},
            {'name': 'brave-lite-stage-3-shard-1-part-1-a2', 'expired': False, 'size_in_bytes': 900},
        ]}]

    def test_reserves_build_budget_and_twice_download_size(self):
        query = lambda _run: self.items
        reserve = 32 * 1024 ** 3 + 2 * 800
        self.assertTrue(eligible(self.env, reserve, 1001, query)[0])
        self.assertFalse(eligible(self.env, reserve - 1, 1001, query)[0])

    def test_late_or_missing_artifacts_are_skipped(self):
        query = lambda _run: self.items
        self.assertFalse(eligible(self.env, 100 * 1024 ** 3, 1000 + 205 * 60, query)[0])
        self.assertFalse(eligible({**self.env, 'RESCUE_SHARD': '2'}, 100 * 1024 ** 3, 1001, query)[0])

    def test_invalid_selection_and_size_fail_closed(self):
        with self.assertRaises(ValueError):
            eligible({**self.env, 'RESCUE_STAGE': '9'}, 100 * 1024 ** 3, 1001, lambda _run: self.items)
        self.items[0]['artifacts'][0]['size_in_bytes'] = None
        with self.assertRaises(ValueError):
            eligible(self.env, 100 * 1024 ** 3, 1001, lambda _run: self.items)


if __name__ == '__main__':
    unittest.main()
