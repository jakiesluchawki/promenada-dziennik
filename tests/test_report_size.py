"""Synthetic-only size recovery; original reader format and source data survive."""
import base64
import contextlib
import copy
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import collector
import publisher
from report_errors import Diagnostics, ReportError
from test_report_diagnostics import previous_report, PASSWORD, MARKER
from bs4 import BeautifulSoup


def attachment(**changes):
    result = {'name': 'synthetic.bin', 'mime': 'application/octet-stream',
              'base64': base64.b64encode(b'synthetic bytes').decode(), 'size': 15}
    result.update(changes)
    return result


class AttachmentCompaction(unittest.TestCase):
    def test_only_identical_successful_records_are_removed(self):
        first = attachment()
        reordered = dict(reversed(list(first.items())))
        distinct = [attachment(name='other.bin'), attachment(mime='other/type'),
                    attachment(base64=base64.b64encode(b'other bytes').decode()),
                    attachment(extra='preserved metadata')]
        failed = {'name': 'missing', 'error': MARKER}
        linked = {'name': 'link', 'url': 'https://example.invalid/file'}
        records = [first, reordered, *distinct, failed, failed, linked, linked]
        before = copy.deepcopy(records)
        self.assertEqual(publisher.unique_attachments(records),
                         [first, *distinct, failed, failed, linked, linked])
        self.assertEqual(records, before)

    def test_load_report_preserves_accounts_messages_archive_and_fallback(self):
        report = previous_report()
        account = report['accounts']['demo']
        source = account['announcements'][0]
        source.update(archived=True, attachments=[attachment(), attachment()])
        account['messages'] = [dict(source, id='demo:message:1', attachments=[attachment(), attachment()])]
        account['sections'] = {'notes': {'text': MARKER, 'custom': MARKER}}
        report['accounts']['other'] = copy.deepcopy(account)
        digest = report.pop('digest')
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / 'snapshot.json').write_text(json.dumps(report))
            (root / 'digest.json').write_text(json.dumps(digest))
            with patch.object(publisher, 'BASE', root), patch.object(publisher, 'secret', return_value=json.dumps({'demo': {}, 'other': {}})):
                compact = publisher.load_report()
        for key in ('demo', 'other'):
            account = compact['accounts'][key]
            self.assertEqual(len(account['messages']), 1)
            self.assertEqual(len(account['announcements']), 1)
            self.assertTrue(account['announcements'][0]['archived'])
            self.assertEqual(account['announcements'][0]['text'], MARKER)
            for kind in ('messages', 'announcements'):
                self.assertEqual(account[kind][0]['attachments'], [attachment()])
            self.assertEqual(account['sections']['notes']['text'], MARKER)
            self.assertEqual(account['sections']['notes']['custom'], MARKER)
        self.assertEqual(compact['digest']['actions'][0]['source_id'], source['id'])

    def collect_duplicate_controls(self, side_effect, extra_controls=''):
        mailbox = BeautifulSoup('<tr><td><a href="/wiadomosci/1/5/1">Message</a></td></tr>', 'html.parser')
        detail = BeautifulSoup('''<div id="body"><div class="container-message-content">Text</div>
          <table><tr><td>synthetic.bin</td><td>
          <button onclick="go('/wiadomosci/pobierz_zalacznik/1/2')">Download</button>
          <span onclick="go('/wiadomosci/pobierz_zalacznik/1/2')">Icon</span>
          </td></tr>''' + extra_controls + '</table></div>', 'html.parser')
        empty = BeautifulSoup('<div id="body"></div>', 'html.parser')
        with patch.object(collector, 'login', return_value=(object(), mailbox, '')), \
             patch.object(collector, 'checked_get', side_effect=[detail] + [empty] * 8), \
             patch.object(collector, 'download_attachment', side_effect=side_effect) as download, \
             patch.object(collector.time, 'sleep'):
            account = collector.collect_account('demo', {})
        return account, download

    def test_duplicate_download_controls_fetch_one_file(self):
        account, download = self.collect_duplicate_controls([attachment()])
        download.assert_called_once()
        self.assertEqual(account['messages'][0]['attachments'], [attachment()])

    def test_failed_control_does_not_block_later_success(self):
        account, download = self.collect_duplicate_controls([RuntimeError('synthetic failure'), attachment()])
        self.assertEqual(download.call_count, 2)
        files = account['messages'][0]['attachments']
        self.assertEqual(files[0]['error'], 'synthetic failure')
        self.assertEqual(files[1], attachment())

    def test_distinct_endpoint_or_filename_is_not_skipped(self):
        controls = '''<tr><td>different.bin</td><td onclick="go('/wiadomosci/pobierz_zalacznik/1/2')">Same endpoint</td></tr>
        <tr><td>synthetic.bin</td><td onclick="go('/wiadomosci/pobierz_zalacznik/1/3')">Different endpoint</td></tr>'''
        records = [attachment(), attachment(name='different.bin'), attachment(base64='b3RoZXI=')]
        account, download = self.collect_duplicate_controls(records, controls)
        self.assertEqual(download.call_count, 3)
        self.assertEqual(account['messages'][0]['attachments'], records)


class SizeAndCompatibility(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for existing web-reader verification')
    def test_existing_web_reader_decrypts_and_ios_attachment_reader_opens_bytes(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        report = previous_report()
        report['accounts']['demo']['announcements'][0]['attachments'] = [attachment()]
        envelope = publisher.encrypt(report, PASSWORD)
        javascript = r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
globalThis.crypto = require('node:crypto').webcrypto;
const {envelope, password, expected} = JSON.parse(fs.readFileSync(0, 'utf8'));
const app = fs.readFileSync('app.js', 'utf8');
// Execute the unchanged deployed reader, not a reimplementation.
eval(app.slice(app.indexOf('function fromB64('), app.indexOf('$("unlock-form").addEventListener')));
const web = fs.readFileSync('ios/Promenada/Web/app.js', 'utf8');
const attachmentUrls = new Set();
const el = (tag, className, text) => ({tag, className, text});
eval(web.slice(web.indexOf('function attachment(f){'), web.indexOf('function doc(m){')));
(async () => {
 const material = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']);
 const recovered = await decrypt(envelope, material);
 assert.deepEqual(recovered, expected);
 const file = recovered.accounts.demo.announcements[0].attachments[0];
 const link = attachment(file);
 assert.equal(Buffer.from(await (await fetch(link.href)).arrayBuffer()).toString(), 'synthetic bytes');
 assert.equal(link.download, file.name);
 for (const url of attachmentUrls) URL.revokeObjectURL(url);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', javascript], cwd=root,
                                input=json.dumps({'envelope': envelope, 'password': PASSWORD, 'expected': report}),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_large_duplicate_payload_recovers_without_changing_unique_bytes(self):
        report = previous_report()
        # Synthetic 8 MB attachment, repeated by two UI controls, exceeds the
        # real envelope cap. Removing the repeated record preserves its bytes.
        data = b'x' * 8_000_000
        file = attachment(base64=base64.b64encode(data).decode(), size=len(data))
        source = report['accounts']['demo']['announcements'][0]
        source['attachments'] = [file, copy.deepcopy(file)]
        oversized = json.dumps(publisher.encrypt(report, PASSWORD), separators=(',', ':'))
        self.assertGreater(len(oversized), publisher.MAX_REPORT_BYTES)
        source['attachments'] = publisher.unique_attachments(source['attachments'])
        envelope = publisher.encrypt(report, PASSWORD)
        payload = json.dumps(envelope, separators=(',', ':'))
        self.assertLess(len(payload), publisher.MAX_REPORT_BYTES)
        self.assertEqual(set(envelope), {'v', 'iterations', 'salt', 'iv', 'ciphertext'})
        self.assertEqual((envelope['v'], envelope['iterations']), (1, 600000))
        recovered = publisher.decrypt(envelope, PASSWORD)
        self.assertEqual(recovered, report)
        self.assertEqual(base64.b64decode(recovered['accounts']['demo']['announcements'][0]['attachments'][0]['base64']), data)

    def test_size_boundary_is_inclusive_and_old_file_survives_failure(self):
        report = previous_report()
        envelope = publisher.encrypt(report, PASSWORD)
        size = len(json.dumps(envelope, separators=(',', ':')).encode())
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            target = root / 'report.enc.json'
            with patch.object(publisher, 'BASE', root), patch.object(publisher, 'SITE', root), \
                 patch.object(publisher, 'load_report', return_value=report), \
                 patch.object(publisher, 'secret', return_value=PASSWORD), \
                 patch.object(publisher, 'encrypt', return_value=envelope), \
                 patch.object(publisher, 'audit'), contextlib.redirect_stdout(io.StringIO()):
                with patch.object(publisher, 'MAX_REPORT_BYTES', size):
                    publisher.build()
                original = target.read_bytes()
                with patch.object(publisher, 'MAX_REPORT_BYTES', size - 1):
                    with self.assertRaises(ReportError) as raised:
                        publisher.build()
                self.assertEqual(raised.exception.code, 'report_too_large')
                self.assertEqual(raised.exception.metrics['encrypted_bytes'], size)
                self.assertEqual(target.read_bytes(), original)
                self.assertFalse((root / 'report.enc.tmp').exists())

    def test_diagnostics_accept_only_fixed_numeric_totals(self):
        metrics = {'encrypted_bytes': 123, 'plaintext_bytes': MARKER,
                   'attachment_bytes': True, MARKER: 456}
        error = ReportError('report_too_large', metrics)
        diagnostics = Diagnostics()
        self.assertEqual(diagnostics.failure(error),
                         'phase=initialise code=report_too_large encrypted_bytes=123')
        for invalid in (-1, 10**12+1, 12.0, None, MARKER):
            self.assertEqual(ReportError('report_too_large', {'attachment_bytes': invalid}).metrics, {})
        self.assertEqual(ReportError('digest_unknown_source', {'encrypted_bytes': 123}).metrics, {})
        report = previous_report()
        report['accounts']['demo']['announcements'][0]['attachments'] = [attachment()]
        totals = publisher.report_size_metrics(report, 123)
        self.assertEqual(totals['attachment_bytes'], len(publisher.canonical(attachment())))
        self.assertEqual(totals['plaintext_bytes'], len(publisher.canonical(report)))
        self.assertNotIn(MARKER, json.dumps(totals))


if __name__ == '__main__':
    unittest.main()
