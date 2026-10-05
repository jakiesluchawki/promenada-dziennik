"""No live report or credentials: exercise read-only measurement with synthetic data."""
import base64
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
import measure_report_size
import publisher


class Measurement(unittest.TestCase):
    def test_read_only_and_fixed_numeric_fields(self):
        record = {'name': 'PRIVATE_MARKER', 'base64': base64.b64encode(b'x'*100).decode(), 'size': 100}
        report = {'schema': 1, 'accounts': {'PRIVATE_MARKER': {'messages': [{'attachments': [record, record]}]}}}
        password = 'synthetic-only'
        raw = json.dumps(publisher.encrypt(report, password), separators=(',', ':')).encode()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'SITE_PASSWORD': password}):
            path = pathlib.Path(temporary) / 'synthetic.enc.json'
            path.write_bytes(raw)
            result = measure_report_size.measure(path)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(path.parent.iterdir()), [path])
        self.assertEqual(result['removed_exact_attachment_duplicates'], 1)
        self.assertGreater(result['saved_encrypted_bytes'], 0)
        self.assertEqual(result['existing_encrypted_bytes'], len(raw))
        self.assertFalse(result['fresh_collection_performed'])
        self.assertFalse(result['report_written'])
        self.assertNotIn('PRIVATE_MARKER', json.dumps(result))
        self.assertTrue(all(type(v) in (int, bool) for v in result.values()))

    def test_no_duplicates_keeps_same_size(self):
        report = {'schema': 1, 'accounts': {}}
        raw = json.dumps(publisher.encrypt(report, 'synthetic-only'), separators=(',', ':')).encode()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'SITE_PASSWORD': 'synthetic-only'}):
            path = pathlib.Path(temporary) / 'synthetic.enc.json'; path.write_bytes(raw)
            result = measure_report_size.measure(path)
        self.assertEqual(result['saved_encrypted_bytes'], 0)
        self.assertEqual(result['removed_exact_attachment_duplicates'], 0)

    def test_failure_never_prints_exception_content(self):
        logs = io.StringIO()
        with patch.object(measure_report_size, 'measure', side_effect=RuntimeError('PRIVATE_MARKER')), contextlib.redirect_stderr(logs):
            self.assertEqual(measure_report_size.main(), 1)
        self.assertNotIn('PRIVATE_MARKER', logs.getvalue())
        self.assertIn('code=unexpected_error', logs.getvalue())
