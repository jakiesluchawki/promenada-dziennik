"""Synthetic-only failure cases: no live account or report fixtures."""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import cloud_run
import collector
import publisher
from report_errors import Diagnostics, ReportError, error_code

MARKER = 'SYNTHETIC_PRIVATE_VALUE_DO_NOT_LOG'
SOURCE = 'demo:announcement:' + MARKER
PASSWORD = 'synthetic-only-parent-password'


def previous_report():
    return {
        'schema': 1,
        'collected_at': '2026-10-02T16:00:00+00:00',
        'accounts': {'demo': {
            'status': 'ok', 'checked_at': '2026-10-02T16:00:00+00:00',
            'messages': [], 'announcements': [{
                'id': SOURCE, 'child': 'demo', 'kind': 'announcement', 'title': MARKER, 'text': MARKER,
                'attachments': [],
            }], 'sections': {},
        }},
        'digest': {'actions': [{
            'child': 'demo', 'source_id': SOURCE, 'title': MARKER, 'text': MARKER,
        }], 'observations': []},
    }


class PublicDiagnostics(unittest.TestCase):
    def test_allowlisted_labels_do_not_serialize_exception_values(self):
        diagnostics = Diagnostics()
        diagnostics.set_phase('collect')
        for error, expected in [
            (RuntimeError(MARKER), 'unexpected_error'),
            (KeyError(MARKER), 'missing_field'),
            (TypeError(MARKER), 'invalid_type'),
            (ValueError(MARKER), 'invalid_value'),
            (OSError(MARKER), 'filesystem_error'),
            (AssertionError(MARKER), 'integrity_check_failed'),
            (json.JSONDecodeError(MARKER, MARKER, 0), 'invalid_json'),
            (ReportError('digest_unknown_source'), 'digest_unknown_source'),
        ]:
            with self.subTest(expected=expected):
                self.assertEqual(diagnostics.failure(error), 'phase=collect code=' + expected)
                self.assertNotIn(MARKER, diagnostics.failure(error))
        diagnostics.set_phase(MARKER)
        self.assertEqual(diagnostics.phase, 'initialise')
        self.assertEqual(error_code(ReportError(MARKER)), 'unexpected_error')

    def test_unknown_digest_source_is_still_rejected_without_its_id(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(publisher, 'BASE', pathlib.Path(temporary)):
            report = previous_report()
            report['accounts']['demo']['announcements'] = []
            digest = report.pop('digest')
            (publisher.BASE / 'snapshot.json').write_text(json.dumps(report))
            (publisher.BASE / 'digest.json').write_text(json.dumps(digest))
            with self.assertRaises(ReportError) as raised:
                publisher.load_report()
            self.assertEqual(raised.exception.code, 'digest_unknown_source')
            self.assertNotIn(MARKER, str(raised.exception))


class CloudRunDiagnostics(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        self.runner = self.root / 'runner'
        self.runner.mkdir()
        self.output = self.root / 'github-output'
        self.target = self.site / 'report.enc.json'
        self.original = json.dumps(publisher.encrypt(previous_report(), PASSWORD))
        self.target.write_text(self.original)
        accounts = json.dumps({'demo': {'display_name': 'Synthetic demo'}})
        secret = lambda name: PASSWORD if name == 'site-password' else accounts
        self.old_bases = collector.BASE, publisher.BASE
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(cloud_run, 'ROOT', self.site))
        self.stack.enter_context(patch.object(publisher, 'SITE', self.site))
        self.stack.enter_context(patch.object(collector, 'secret', side_effect=secret))
        self.stack.enter_context(patch.object(publisher, 'secret', side_effect=secret))
        self.stack.enter_context(patch.object(publisher, 'audit'))
        self.stack.enter_context(patch.dict(os.environ, {
            'RUNNER_TEMP': str(self.runner), 'GITHUB_OUTPUT': str(self.output),
            'PARENT_REFRESH_CONFIG': '',
        }))
        self.stage = self.stack.enter_context(patch('stage_site.stage'))
        self.work_paths = []

    def collect(self, remove_source=False, account_failure=False):
        self.work_paths.append(collector.BASE)
        self.assertEqual(collector.BASE.stat().st_mode & 0o777, 0o700)
        snapshot = json.loads((collector.BASE / 'snapshot.json').read_text())
        if remove_source:
            snapshot['accounts']['demo']['announcements'] = []
        if account_failure:
            snapshot['accounts']['demo'].update(status='error', error=MARKER)
        (collector.BASE / 'snapshot.json').write_text(json.dumps(snapshot))
        print(MARKER)
        print(MARKER, file=sys.stderr)
        if account_failure:
            raise SystemExit(2)

    def run_cloud(self, collect):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(collector, 'main', side_effect=collect), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cloud_run.run()
        logs = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(MARKER, logs)
        self.assertNotIn(PASSWORD, logs)
        self.assertNotIn(str(self.root), logs)
        self.assertEqual(list(self.runner.iterdir()), [])
        self.assertTrue(all(not path.exists() for path in self.work_paths))
        self.assertEqual((collector.BASE, publisher.BASE), self.old_bases)
        return result, logs

    def test_vanished_referenced_announcement_is_preserved_as_historical_source(self):
        result, logs = self.run_cloud(lambda: self.collect(remove_source=True))
        self.assertEqual(result, 0)
        report = publisher.decrypt(json.loads(self.target.read_text()), PASSWORD)
        source = report['accounts']['demo']['announcements'][0]
        self.assertEqual(source['id'], SOURCE)
        self.assertEqual(source['title'], 'Archiwum · ' + MARKER)
        self.assertEqual(source['text'], MARKER)
        self.assertTrue(source['archived'])
        self.assertEqual(self.output.read_text(), 'healthy=true\n')

    def test_unverifiable_source_is_still_rejected_without_changing_ciphertext(self):
        previous = previous_report()
        previous['accounts']['demo']['announcements'] = []
        self.target.write_text(json.dumps(publisher.encrypt(previous, PASSWORD)))
        original = self.target.read_text()
        result, logs = self.run_cloud(self.collect)
        self.assertEqual(result, 1)
        self.assertIn('phase=reconcile_sources code=digest_unknown_source', logs)
        self.assertEqual(self.target.read_text(), original)
        self.assertFalse(self.output.exists())
        self.stage.assert_not_called()

    def test_collection_exception_is_redacted_and_plaintext_is_removed(self):
        def fail():
            self.collect()
            raise RuntimeError(MARKER)
        result, logs = self.run_cloud(fail)
        self.assertEqual(result, 1)
        self.assertIn('phase=collect code=unexpected_error', logs)
        self.assertEqual(self.target.read_text(), self.original)
        self.stage.assert_not_called()

    def test_decryption_failure_is_identified_without_credentials(self):
        self.target.write_text(json.dumps(publisher.encrypt(previous_report(), PASSWORD + '-wrong')))
        result, logs = self.run_cloud(self.collect)
        self.assertEqual(result, 1)
        self.assertIn('phase=decrypt_previous code=decryption_failed', logs)
        self.stage.assert_not_called()

    def test_success_keeps_health_and_source_validation_behavior(self):
        result, logs = self.run_cloud(self.collect)
        self.assertEqual(result, 0)
        self.assertIn('All accounts refreshed.', logs)
        self.assertEqual(self.output.read_text(), 'healthy=true\n')
        report = publisher.decrypt(json.loads(self.target.read_text()), PASSWORD)
        self.assertEqual(report['digest']['actions'][0]['source_id'], SOURCE)
        self.stage.assert_called_once_with(self.site)

    def test_account_warning_remains_a_warning_not_an_unhandled_error(self):
        result, logs = self.run_cloud(lambda: self.collect(account_failure=True))
        self.assertEqual(result, 0)
        self.assertIn('Some accounts require attention', logs)
        self.assertEqual(self.output.read_text(), 'healthy=false\n')
        report = publisher.decrypt(json.loads(self.target.read_text()), PASSWORD)
        self.assertEqual(report['accounts']['demo']['status'], 'error')
        self.stage.assert_called_once_with(self.site)

    def test_audit_failure_emits_only_fixed_labels(self):
        with patch.object(publisher, 'audit', side_effect=ReportError('plaintext_public_file')):
            result, logs = self.run_cloud(self.collect)
        self.assertEqual(result, 1)
        self.assertIn('phase=audit_public_files code=plaintext_public_file', logs)
        self.assertFalse(self.output.exists())
        self.stage.assert_not_called()

    def test_oversized_envelope_is_rejected_before_replacing_ciphertext(self):
        with patch.object(publisher, 'MAX_REPORT_BYTES', 1):
            result, logs = self.run_cloud(self.collect)
        self.assertEqual(result, 1)
        self.assertIn('phase=write_ciphertext code=report_too_large', logs)
        self.assertEqual(self.target.read_text(), self.original)
        self.assertFalse(self.output.exists())
        self.stage.assert_not_called()


if __name__ == '__main__':
    unittest.main()
