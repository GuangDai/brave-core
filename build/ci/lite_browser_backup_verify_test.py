#!/usr/bin/env python3
"""Tests for strict, offline browser-verification artifact checks."""

import json
from pathlib import Path
import tempfile
import unittest

import lite_browser_backup_verify as verify
import lite_browser_checkpoint as checkpoint
import lite_browser_report as report
import lite_browser_verify as browser
from lite_shard_cache import TARGETS, entries


class BrowserBackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.expected = verify.context('example/project', checkpoint.SOURCE, '1' * 40, '2' * 64, True)
        self.identity = {'repository': 'example/project', 'commit': checkpoint.SOURCE, 'architecture': 'arm64'}

    def cache(self):
        path = self.root / 'brave-lite-verify-stage-1-shard-5-part-1-a1'
        (path / 'cache/aa').mkdir(parents=True)
        (path / 'cache/aa/object').write_bytes(b'compiler result')
        manifest = {'version': 1, 'identity': self.identity, 'shard': '5', 'target': TARGETS['5'],
                    'part': 1, 'outcome': 'checkpoint', 'actual_build_target': 'brave_browser_tests',
                    'cache_purpose': 'browser-verification', 'verification_provenance': self.expected,
                    'files': entries(path / 'cache')}
        (path / 'manifest.json').write_text(json.dumps(manifest))
        return path

    def saved_checkpoint(self):
        folder = self.root / 'brave-lite-verify-s1-a1-manifest'
        folder.mkdir()
        volumes = []
        for part in ('part-aa', 'part-ab'):
            volume_dir = self.root / f'brave-lite-verify-s1-a1-{part}'
            volume_dir.mkdir()
            path = volume_dir / part
            path.write_bytes(part.encode())
            volumes.append({'name': part, 'size': path.stat().st_size, 'sha256': checkpoint.sha256(path)})
        manifest = {'version': 1, 'identity': self.identity, **self.expected,
                    'checkpoint_kind': checkpoint.KIND, 'test_compile_outcome': 'checkpoint',
                    'test_compile_reason': 'time', 'volumes': volumes}
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        return folder

    def results(self, status='success'):
        path = self.root / 'brave-lite-browser-test-results-a1'
        path.mkdir()
        (path / 'provenance.json').write_text(json.dumps(self.expected))
        if status == 'success':
            results = path / 'results'
            results.mkdir()
            tests = browser.selected_tests(True)
            (results / 'expected-tests.json').write_text(json.dumps(list(tests)))
            listing = ''.join(f'{suite}.\n  {name}\n' for suite, name in (item.rsplit('.', 1) for item in tests))
            (results / 'list.stdout.log').write_text(listing)
            for name in ('list.stderr.log', 'run.stdout.log', 'run.stderr.log'):
                (results / name).write_text('')
            (results / 'summary.json').write_text(json.dumps({'per_iteration_data': [
                {name: [{'status': 'SUCCESS'}] for name in tests}]}))
            (path / 'controller.log').write_text('complete')
        report.record(path, 'complete', 'next', 'success', status)
        return path

    def test_cache_validates_identity_purpose_provenance_and_hash(self):
        path = self.cache()
        self.assertEqual(verify.verify_cache(path, self.expected)['files'], 1)
        (path / 'cache/aa/object').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Cache files differ'):
            verify.verify_cache(path, self.expected)

    def test_cache_rejects_wrong_purpose_or_missing_provenance(self):
        path = self.cache()
        manifest = json.loads((path / 'manifest.json').read_text())
        for key, value in (('cache_purpose', 'app'), ('verification_provenance', {})):
            changed = {**manifest, key: value}
            (path / 'manifest.json').write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                verify.verify_cache(path, self.expected)

    def test_cache_rejects_symlinks_and_invalid_name(self):
        path = self.cache()
        (path / 'cache/aa/link').symlink_to('object')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            verify.verify_cache(path, self.expected)
        invalid = self.root / 'brave-lite-verify-stage-1-shard-5-part-1-a0'
        invalid.mkdir()
        with self.assertRaisesRegex(ValueError, 'name'):
            verify.verify_cache(invalid, self.expected)

    def test_checkpoint_requires_all_verified_volumes_and_provenance(self):
        folder = self.saved_checkpoint()
        self.assertEqual(len(verify.verify_checkpoint_manifest(folder, self.expected)['volumes']), 2)
        first = self.root / 'brave-lite-verify-s1-a1-part-aa'
        self.assertEqual(verify.verify_checkpoint_volume(first, folder, self.expected)['name'], 'part-aa')
        self.assertEqual(verify.verify_checkpoint(self.root, '1', self.expected)['volumes'], 2)
        path = self.root / 'brave-lite-verify-s1-a1-part-ab/part-ab'
        path.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'volume differs'):
            verify.verify_checkpoint(self.root, '1', self.expected)
        path.write_bytes(b'part-ab')
        data = json.loads((folder / 'manifest.json').read_text())
        data['test_repository'] = 'other/project'
        (folder / 'manifest.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Provenance differs'):
            verify.verify_checkpoint(self.root, '1', self.expected)

    def test_checkpoint_rejects_missing_or_extra_volume(self):
        self.saved_checkpoint()
        extra = self.root / 'brave-lite-verify-s1-a1-part-ac'
        extra.mkdir()
        with self.assertRaisesRegex(ValueError, 'Unexpected or missing'):
            verify.verify_checkpoint(self.root, '1', self.expected)
        extra.rmdir()
        missing = self.root / 'brave-lite-verify-s1-a1-part-ab/part-ab'
        missing.unlink()
        with self.assertRaisesRegex(ValueError, 'Unexpected volume contents'):
            verify.verify_checkpoint(self.root, '1', self.expected)

    def test_success_requires_listing_summary_logs_and_matching_hashes(self):
        path = self.results()
        self.assertEqual(verify.verify_results(path, self.expected)['test_status'], 'success')
        (path / 'results/run.stdout.log').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checksum manifest'):
            verify.verify_results(path, self.expected)

    def test_success_rejects_missing_evidence_even_if_manifest_is_recomputed(self):
        path = self.results()
        (path / 'results/summary.json').unlink()
        report.record(path, 'complete', 'next', 'success', 'success')
        with self.assertRaisesRegex(ValueError, 'evidence is incomplete'):
            verify.verify_results(path, self.expected)

    def test_success_rejects_unexecuted_or_skipped_tests(self):
        path = self.results()
        summary = path / 'results/summary.json'
        data = json.loads(summary.read_text())
        data['per_iteration_data'][0][browser.selected_tests(True)[0]][0]['status'] = 'SKIPPED'
        summary.write_text(json.dumps(data))
        report.record(path, 'complete', 'next', 'success', 'success')
        with self.assertRaisesRegex(ValueError, 'did not pass'):
            verify.verify_results(path, self.expected)

    def test_failed_test_artifact_can_be_saved_without_claiming_success(self):
        path = self.results('failure')
        self.assertEqual(verify.verify_results(path, self.expected)['test_status'], 'failure')

    def test_results_reject_wrong_source_workflow_or_app(self):
        path = self.results()
        for key, value in (('test_source_commit', '3' * 40),
                           ('verification_workflow_commit', '4' * 40), ('app_binary_sha256', '5' * 64)):
            changed = {**self.expected, key: value}
            with self.assertRaisesRegex(ValueError, 'Provenance differs'):
                verify.verify_results(path, changed)


if __name__ == '__main__':
    unittest.main()
