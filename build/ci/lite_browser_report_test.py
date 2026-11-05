#!/usr/bin/env python3
"""Test explicit browser-report state and file checksums."""

import json
from pathlib import Path
import tempfile
import unittest

import lite_browser_report as report


PROVENANCE = {'test_repository': 'example/project', 'test_architecture': 'arm64',
              'test_source_commit': 'a' * 40, 'test_overlay': False,
              'test_overlay_commit': '', 'test_overlay_sha256': '',
              'app_binary_sha256': 'b' * 64, 'verification_workflow_commit': 'c' * 40}


class BrowserReportTest(unittest.TestCase):
    def test_failed_or_completed_test_evidence_is_checksum_recorded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            (root / 'provenance.json').write_text(json.dumps(PROVENANCE))
            (root / 'results').mkdir()
            (root / 'results/list.stdout.log').write_text('test list')
            report.record(root, 'complete', 'next', 'success', 'failure')
            manifest = json.loads((root / report.MANIFEST).read_text())
            self.assertEqual(manifest['test_status'], 'failure')
            self.assertEqual(manifest['files'], report.entries(root))
            (root / 'results/list.stdout.log').write_text('changed')
            self.assertNotEqual(manifest['files'], report.entries(root))

    def test_missing_or_contradictory_status_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            (root / 'provenance.json').write_text(json.dumps(PROVENANCE))
            with self.assertRaises(ValueError):
                report.record(root, 'complete', '', 'success', '')
            with self.assertRaises(ValueError):
                report.record(root, 'checkpoint', 'time', '', 'success')


if __name__ == '__main__':
    unittest.main()
