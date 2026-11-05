#!/usr/bin/env python3
"""Restore verified checkpoint volumes directly from GitHub artifact streams."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import lite_checkpoint


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_request(url, token):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "brave-lite-checkpoint",
    })
    return urllib.request.build_opener(NoRedirect).open(request, timeout=60)


def artifacts(repository, run_id, token, api_url="https://api.github.com"):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository")
    if not run_id.isdigit() or not token:
        raise ValueError("A run ID and GitHub token are required")
    found = {}
    page = 1
    while True:
        url = f"{api_url}/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100&page={page}"
        with api_request(url, token) as response:
            values = json.load(response)["artifacts"]
        for item in values:
            if not item.get("expired"):
                name = item["name"]
                if name in found:
                    raise RuntimeError(f"Duplicate artifact name: {name}")
                found[name] = str(item["id"])
        if len(values) < 100:
            return found
        page += 1


def open_artifact(repository, artifact_id, token, api_url="https://api.github.com"):
    if not artifact_id.isdigit():
        raise ValueError("Invalid artifact ID")
    url = f"{api_url}/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "brave-lite-checkpoint",
    })
    opener = urllib.request.build_opener(NoRedirect)
    try:
        return opener.open(request, timeout=60)
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            raise
        location = error.headers.get("Location", "")
    if urllib.parse.urlsplit(location).scheme != "https":
        raise RuntimeError("Artifact redirect did not use HTTPS")
    # Open the signed storage URL without forwarding the GitHub token.
    return urllib.request.urlopen(location, timeout=60)


def read_exact(stream, size):
    result = bytearray()
    while len(result) < size:
        block = stream.read(size - len(result))
        if not block:
            raise RuntimeError("Unexpected end of artifact")
        result.extend(block)
    return bytes(result)


def stream_zip_member(stream, output, volume):
    header = read_exact(stream, 30)
    (signature, _version, flags, method, _time, _date, _crc, compressed,
     uncompressed, name_length, extra_length) = struct.unpack("<IHHHHHIIIHH", header)
    if signature != 0x04034B50 or flags & 1 or method != 0:
        raise RuntimeError("Checkpoint artifact is not a stored ZIP member")
    name = read_exact(stream, name_length).decode("utf-8")
    read_exact(stream, extra_length)
    if name != volume["name"]:
        raise RuntimeError(f"Unexpected checkpoint member: {name}")
    size = volume["size"]
    if compressed not in (0, 0xFFFFFFFF, size) or uncompressed not in (0, 0xFFFFFFFF, size):
        raise RuntimeError(f"Unexpected checkpoint member size: {name}")
    checksum = hashlib.sha256()
    remaining = size
    while remaining:
        block = stream.read(min(8 * 1024 * 1024, remaining))
        if not block:
            raise RuntimeError(f"Truncated checkpoint member: {name}")
        checksum.update(block)
        output.write(block)
        remaining -= len(block)
    if checksum.hexdigest() != volume["sha256"]:
        raise RuntimeError(f"Checkpoint volume failed verification: {name}")
    print(f"Streamed and verified {name}: {size} bytes", flush=True)


def restore(workspace, manifest, build_identity, repository, run_id, attempt,
            stage, token, api_url="https://api.github.com"):
    if not attempt.isdigit() or not re.fullmatch(r"[1-8]", stage):
        raise ValueError("Invalid checkpoint stage or attempt")
    workspace = workspace.resolve()
    lite_checkpoint.prepare_workspace(workspace)
    volumes = lite_checkpoint.validate_manifest(manifest, build_identity)
    available = artifacts(repository, run_id, token, api_url)
    names = [f"brave-lite-s{stage}-a{attempt}-{item['name']}" for item in volumes]
    if any(name not in available for name in names):
        raise RuntimeError("One or more checkpoint volume artifacts are unavailable")

    decompressor = subprocess.Popen(["zstd", "-d", "-q", "-c"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    extractor = subprocess.Popen(["tar", "-C", str(workspace), "-xf", "-"],
                                 stdin=decompressor.stdout)
    decompressor.stdout.close()
    try:
        for name, volume in zip(names, volumes):
            with open_artifact(repository, available[name], token, api_url) as stream:
                stream_zip_member(stream, decompressor.stdin, volume)
        decompressor.stdin.close()
        if decompressor.wait() != 0 or extractor.wait() != 0:
            raise RuntimeError("Checkpoint extraction failed")
    except BaseException:
        if not decompressor.stdin.closed:
            try:
                decompressor.stdin.close()
            except BrokenPipeError:
                pass
        for process in (decompressor, extractor):
            if process.poll() is None:
                process.terminate()
            process.wait()
        raise
    print(f"Restored {len(volumes)} streamed checkpoint volume(s)", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    build_identity = lite_checkpoint.identity(args.repository, args.commit, args.workspace)
    restore(args.workspace, json.loads(args.manifest.read_text()), build_identity,
            args.repository, args.run_id, args.attempt, args.stage,
            os.environ.get("GH_TOKEN", ""))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError,
            urllib.error.URLError) as error:
        print(f"Streamed checkpoint error: {error}", file=sys.stderr)
        sys.exit(1)
