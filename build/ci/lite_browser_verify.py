#!/usr/bin/env python3
"""List and run a small fixed set of browser tests, rejecting empty results."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


BASE_TESTS = (
    'BraveAutofillBrowserTest.AutofillIsNotAllowedInPrivateWindows',
    'PasswordManagerTest.SavePasswordAndOpenSettingsNoErrors',
    'InProcessBrowserTest.TranslationIsUnavailable',
)
OVERLAY_TEST = 'BraveTranslateBrowserTest.ManualTranslationIsUnavailable'


def selected_tests(overlay):
    return BASE_TESTS + ((OVERLAY_TEST,) if overlay else ())


def parse_test_list(output):
    tests, suite = set(), None
    for line in output.splitlines():
        if match := re.fullmatch(r'([A-Za-z_][A-Za-z0-9_./]*)\.\s*(?:#.*)?', line):
            suite = match.group(1)
        elif match := re.fullmatch(r'\s{2}([A-Za-z_][A-Za-z0-9_./]*)\s*(?:#.*)?', line):
            if suite:
                tests.add(f'{suite}.{match.group(1)}')
        elif line and not line[0].isspace():
            suite = None
    return tests


def verify_summary(summary, expected):
    if not isinstance(summary, dict):
        raise ValueError('Test summary is not an object')
    iterations = summary.get('per_iteration_data')
    if not isinstance(iterations, list) or len(iterations) != 1 or not isinstance(iterations[0], dict):
        raise ValueError('Expected exactly one test iteration')
    iteration = iterations[0]
    if set(iteration) != set(expected):
        raise ValueError(f'Executed tests differ: expected {sorted(expected)}, got {sorted(iteration)}')
    for name in expected:
        results = iteration[name]
        if (not isinstance(results, list) or len(results) != 1
                or not isinstance(results[0], dict) or results[0].get('status') != 'SUCCESS'):
            raise ValueError(f'Test did not pass exactly once: {name}')


def invoke(command, cwd, stdout_path, stderr_path, timeout):
    with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
        result = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f'Test command failed with exit code {result.returncode}')


def verify(binary, output, overlay=False):
    binary = binary.resolve()
    if not binary.is_file():
        raise ValueError('Browser-test binary is missing')
    output.mkdir(parents=True, exist_ok=False)
    tests = selected_tests(overlay)
    test_filter = ':'.join(tests)
    (output / 'expected-tests.json').write_text(json.dumps(list(tests), indent=2) + '\n')
    listing = output / 'list.stdout.log'
    invoke([str(binary), '--gtest_list_tests', f'--gtest_filter={test_filter}'], binary.parent,
           listing, output / 'list.stderr.log', 120)
    found = parse_test_list(listing.read_text(errors='replace'))
    missing = set(tests) - found
    if missing:
        raise ValueError(f'Expected tests were not listed: {sorted(missing)}')
    summary = output / 'summary.json'
    invoke([str(binary), f'--gtest_filter={test_filter}', '--test-launcher-jobs=1',
            '--test-launcher-retry-limit=0', f'--test-launcher-summary-output={summary}'],
           binary.parent, output / 'run.stdout.log', output / 'run.stderr.log', 900)
    verify_summary(json.loads(summary.read_text()), tests)
    print(f'Verified {len(tests)} explicitly listed and executed browser tests', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--translation-overlay', action='store_true')
    args = parser.parse_args()
    verify(args.binary, args.output, args.translation_overlay)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Browser verification failed: {error}', file=sys.stderr)
        sys.exit(1)
