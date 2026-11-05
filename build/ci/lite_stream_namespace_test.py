#!/usr/bin/env python3
"""Verify browser-test checkpoints remain separate from app checkpoints."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import lite_checkpoint
import lite_stream_checkpoint


class NamespaceTest(unittest.TestCase):
    def test_restores_only_the_selected_namespace(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / 'object.o').write_bytes(os.urandom(1024))
            identity = {'repository': 'example/project', 'commit': 'abc',
                        'workspace': '/workspace', 'architecture': 'arm64',
                        'image_os': 'macos26', 'macos_version': '26.1',
                        'xcode_version': '26', 'sdk_version': '26'}
            lite_checkpoint.save(source, root / 'saved', identity)
            manifest = json.loads((root / 'saved/manifest.json').read_text())
            self.assertEqual(len(manifest['volumes']), 1)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
                archive.write(root / 'saved/part-aa', 'part-aa')
            names = {'brave-lite-verify-s1-a1-part-aa': '123'}
            with patch('lite_stream_checkpoint.artifacts', return_value=names), \
                 patch('lite_stream_checkpoint.open_artifact', side_effect=lambda *_: io.BytesIO(buffer.getvalue())):
                with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                    lite_stream_checkpoint.restore(root / 'production', manifest, identity,
                                                   'example/project', '42', '1', '1', 'token')
                lite_stream_checkpoint.restore(root / 'verification', manifest, identity,
                                               'example/project', '42', '1', '1', 'token',
                                               namespace='brave-lite-verify')
            self.assertEqual((root / 'verification/object.o').read_bytes(),
                             (source / 'object.o').read_bytes())


if __name__ == '__main__':
    unittest.main()
