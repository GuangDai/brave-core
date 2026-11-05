#!/usr/bin/env python3
"""Compile and exercise a small translation-patch fixture on the CI runner."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'build/ci/lite_translation_clang_fixture.cc'


def validate_fixture():
    fixture = FIXTURE.read_text()
    prefs = (ROOT / 'patches/components-translate-core-browser-translate_prefs.cc.patch').read_text()
    manager = (ROOT / 'patches/components-translate-core-browser-translate_manager.cc.patch').read_text()
    expressions = [line[1:].strip() for line in prefs.splitlines() if line.startswith('+  return ')]
    if len(expressions) != 2 or any(fixture.count(expression) != 1 for expression in expressions):
        raise RuntimeError('Translation preferences fixture does not match the patch')
    guard = '#if BUILDFLAG(IS_MAC)'
    if manager.count('+' + guard) != 2 or fixture.count(guard) != 2:
        raise RuntimeError('Translation manager fixture does not match the platform guards')
    if manager.count('+#else') != 2 or manager.count('+#endif') != 2:
        raise RuntimeError('Translation manager patch no longer matches the fixture branches')


def main():
    validate_fixture()
    compiler = os.environ.get('CXX', 'clang++')
    flags = ['-std=c++23', '-Wall', '-Wextra', '-Wunreachable-code',
             '-Wunreachable-code-aggressive', '-Werror']
    with tempfile.TemporaryDirectory(prefix='lite-translation-check-') as tmp:
        tmp = Path(tmp)
        for mac in (0, 1):
            output = tmp / f'translation-{mac}'
            subprocess.run([compiler, *flags, f'-DLITE_TEST_IS_MAC={mac}',
                            str(FIXTURE), '-o', str(output)], check=True)
            subprocess.run([str(output)], check=True)
            print(f'Translation compiler and behavior fixture passed: IS_MAC={mac}', flush=True)


if __name__ == '__main__':
    main()
