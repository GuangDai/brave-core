#!/usr/bin/env python3
"""Test streaming integrity, artifact ZIP layout and credential handling."""

import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

import lite_checkpoint
import lite_stream_checkpoint


class NonSeekable(io.BytesIO):
    def seekable(self):
        return False

    def seek(self, *args):
        raise io.UnsupportedOperation("not seekable")


class Zip64ZeroStream:
    def __init__(self, name, size):
        name_bytes = name.encode()
        extra = struct.pack('<HHQQ', 1, 16, size, size)
        self.header = (struct.pack('<IHHHHHIIIHH', 0x04034B50, 45, 8, 0, 0, 0, 0,
                                   0xFFFFFFFF, 0xFFFFFFFF, len(name_bytes), len(extra))
                       + name_bytes + extra)
        self.remaining = size

    def read(self, size):
        if self.header:
            data, self.header = self.header[:size], self.header[size:]
            return data
        count = min(size, self.remaining)
        self.remaining -= count
        return b'\0' * count


class CountingSink:
    def __init__(self):
        self.size = 0

    def write(self, data):
        self.size += len(data)


def archive(name, data, method=zipfile.ZIP_STORED):
    buffer = NonSeekable()
    with zipfile.ZipFile(buffer, "w", compression=method) as output:
        output.writestr(name, data)
    return buffer.getvalue()


class StreamCheckpointTest(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[2] / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {"repository": "example/project", "commit": "abc",
                         "workspace": "/workspace", "architecture": "arm64",
                         "image_os": "macos26", "image_version": "one",
                         "macos_version": "26.6.2", "xcode_version": "26.6",
                         "sdk_version": "26.5"}

    def test_zip_stream_validates_size_name_and_hash(self):
        data = os.urandom(90_000)
        volume = {"name": "part-aa", "size": len(data),
                  "sha256": hashlib.sha256(data).hexdigest()}
        output = io.BytesIO()
        lite_stream_checkpoint.stream_zip_member(io.BytesIO(archive("part-aa", data)), output, volume)
        self.assertEqual(output.getvalue(), data)
        with self.assertRaisesRegex(RuntimeError, "failed verification"):
            lite_stream_checkpoint.stream_zip_member(io.BytesIO(archive("part-aa", data)),
                                                     io.BytesIO(), {**volume, "sha256": "0" * 64})
        with self.assertRaisesRegex(RuntimeError, "Unexpected checkpoint member"):
            lite_stream_checkpoint.stream_zip_member(io.BytesIO(archive("other", data)),
                                                     io.BytesIO(), volume)
        with self.assertRaisesRegex(RuntimeError, "stored ZIP"):
            lite_stream_checkpoint.stream_zip_member(io.BytesIO(archive("part-aa", data, zipfile.ZIP_DEFLATED)),
                                                     io.BytesIO(), volume)

    @unittest.skipUnless(os.environ.get('LITE_LARGE_STREAM_TEST') == '1',
                         'Large streamed boundary test is run separately in CI')
    def test_zip64_stored_member_at_four_gib_boundary(self):
        size = 4 * 1024 ** 3
        block = b'\0' * (8 * 1024 ** 2)
        digest = hashlib.sha256()
        for _ in range(size // len(block)):
            digest.update(block)
        volume = {'name': 'part-aa', 'size': size, 'sha256': digest.hexdigest()}
        output = CountingSink()
        lite_stream_checkpoint.stream_zip_member(Zip64ZeroStream('part-aa', size), output, volume)
        self.assertEqual(output.size, size)

    def test_multivolume_restore_without_downloaded_archives(self):
        source = self.root / "source"
        source.mkdir()
        data = os.urandom(250_000)
        (source / "object.o").write_bytes(data)
        saved = self.root / "checkpoint"
        lite_checkpoint.save(source, saved, self.identity, 100_000)
        manifest = json.loads((saved / "manifest.json").read_text())
        blobs = {}
        names = {}
        for index, volume in enumerate(manifest["volumes"]):
            artifact_name = f"brave-lite-s1-a1-{volume['name']}"
            names[artifact_name] = str(index)
            blobs[str(index)] = archive(volume["name"], (saved / volume["name"]).read_bytes())
        with patch("lite_stream_checkpoint.artifacts", return_value=names), \
                patch("lite_stream_checkpoint.open_artifact", side_effect=lambda _r, i, _t, _a: io.BytesIO(blobs[i])):
            lite_stream_checkpoint.restore(self.root / "restored", manifest, self.identity,
                                           "example/project", "42", "1", "1", "token")
        self.assertEqual((self.root / "restored" / "object.o").read_bytes(), data)

    def test_github_token_is_not_forwarded_to_redirect(self):
        redirect = urllib.error.HTTPError("https://api.github.com/artifact", 302, "Found",
                                          {"Location": "https://example.test/signed"}, None)
        with patch("lite_stream_checkpoint.urllib.request.build_opener") as factory, \
                patch("lite_stream_checkpoint.urllib.request.urlopen") as open_url:
            factory.return_value.open.side_effect = redirect
            lite_stream_checkpoint.open_artifact("example/project", "42", "secret")
            args, kwargs = open_url.call_args
            self.assertEqual(args, ("https://example.test/signed",))
            self.assertEqual(kwargs, {"timeout": 60})


if __name__ == "__main__":
    unittest.main()
