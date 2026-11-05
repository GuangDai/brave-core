#!/usr/bin/env python3
"""Exercise browser-test result validation using a fake test launcher."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import lite_browser_verify


FAKE = '''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
tests = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--gtest_filter=')).split(':')
if '--gtest_list_tests' in sys.argv:
    if os.environ.get('FAKE_MODE') == 'missing':
        tests = tests[:-1]
    for name in tests:
        suite, test = name.split('.', 1)
        print(suite + '.')
        print('  ' + test)
else:
    assert '--test-launcher-jobs=1' in sys.argv
    assert '--test-launcher-retry-limit=0' in sys.argv
    target = Path(next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--test-launcher-summary-output=')))
    mode = os.environ.get('FAKE_MODE')
    values = {name: [{'status': 'SKIPPED' if mode == 'skip' else 'SUCCESS'}] for name in tests}
    if mode == 'empty':
        values = {}
    target.write_text(json.dumps({'per_iteration_data': [values]}))
    if mode == 'failed':
        sys.exit(1)
'''


class BrowserVerifyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / 'fake_browser_tests'
        self.binary.write_text(FAKE)
        self.binary.chmod(0o755)
        self.output = self.root / 'results'

    def test_success_checks_all_base_and_overlay_tests(self):
        with patch.dict(os.environ, {'FAKE_MODE': 'success'}):
            lite_browser_verify.verify(self.binary, self.output, overlay=True)
        expected = json.loads((self.output / 'expected-tests.json').read_text())
        self.assertEqual(expected, list(lite_browser_verify.selected_tests(True)))
        self.assertTrue((self.output / 'summary.json').is_file())

    def test_missing_listed_test_is_rejected_before_execution(self):
        with patch.dict(os.environ, {'FAKE_MODE': 'missing'}):
            with self.assertRaisesRegex(ValueError, 'not listed'):
                lite_browser_verify.verify(self.binary, self.output)
        self.assertFalse((self.output / 'summary.json').exists())
        self.assertTrue((self.output / 'list.stdout.log').exists())

    def test_empty_or_skipped_summary_and_nonzero_exit_are_rejected(self):
        for mode in ('empty', 'skip', 'failed'):
            with self.subTest(mode=mode), patch.dict(os.environ, {'FAKE_MODE': mode}):
                output = self.root / f'results-{mode}'
                with self.assertRaises((ValueError, RuntimeError)):
                    lite_browser_verify.verify(self.binary, output)
                self.assertTrue((output / 'run.stdout.log').exists())


if __name__ == '__main__':
    unittest.main()
