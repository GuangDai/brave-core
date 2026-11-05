#!/usr/bin/env python3
"""Test restored Siso configuration compatibility checks."""

from pathlib import Path
import tempfile
import unittest

import lite_siso_config_verify


class SisoConfigTest(unittest.TestCase):
    def test_installed_config_must_match_the_fixed_source(self):
        repository = Path(__file__).resolve().parents[2]
        test_root = repository / '.lite-validation'
        test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as temporary:
            src = Path(temporary)
            original = src / 'brave/build/config/siso/brave_siso_config.star'
            applied = src / 'build/config/siso/brave_siso_config.star'
            original.parent.mkdir(parents=True)
            applied.parent.mkdir(parents=True)
            data = (repository / 'build/config/siso/brave_siso_config.star').read_bytes()
            original.write_bytes(data)
            applied.write_bytes(data)
            lite_siso_config_verify.verify(src)
            applied.write_bytes(b'different')
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                lite_siso_config_verify.verify(src)
            original.write_bytes(b'old config')
            applied.write_bytes(b'old config')
            with self.assertRaisesRegex(RuntimeError, 'lacks'):
                lite_siso_config_verify.verify(src)


if __name__ == '__main__':
    unittest.main()
