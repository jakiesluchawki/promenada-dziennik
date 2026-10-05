"""Static native regression guards only: these do NOT compile or run iOS code."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORE = (ROOT / 'ios/Promenada/ReportStore.swift').read_text()
MODEL = (ROOT / 'ios/Promenada/JournalModel.swift').read_text()


class NativeAttachmentSourceContract(unittest.TestCase):
    def test_v2_transport_falls_back_only_on_not_found(self):
        section = STORE.split('private func downloadReport(', 1)[1].split('    func load(', 1)[0]
        self.assertIn('access.v2Endpoint', section)
        self.assertIn('catch ReportDownloadError.notFound', section)
        self.assertEqual(section.count('access.endpoint'), 1)
        self.assertNotIn('catch {', section)

    def test_live_v2_selection_rejects_legacy_schema_before_cache(self):
        transport = STORE.split('private func downloadReport(', 1)[1].split('    func load(', 1)[0]
        self.assertIn('return (bytes, true)', transport)
        self.assertIn('return (bytes, false)', transport)
        load = STORE.split('    func load(', 1)[1].split('    private func protectedWrite', 1)[0]
        self.assertIn('requiresSchema2 = result.requiresSchema2', load)
        self.assertIn('encrypted = cached; requiresSchema2 = false; offline = true', load)
        self.assertLess(load.index('requiresSchema2: requiresSchema2'), load.index('try protectedWrite'))
        self.assertIn('return !requiresSchema2 || schema == 2', STORE)

    def test_bounded_transport_rejects_redirects_and_overflow_before_append(self):
        section = STORE.split('final class BoundedReportDownload:', 1)[1].split('struct EncryptedAttachment:', 1)[0]
        self.assertIn('completionHandler(nil)', section)
        self.assertIn('response.url?.absoluteString == request.url?.absoluteString', section)
        self.assertIn('response.expectedContentLength <= Int64(maximum)', section)
        self.assertLess(section.index('data.count <= maximum - buffer.count'), section.index('buffer.append(data)'))
        self.assertIn('withTaskCancellationHandler', section)
        self.assertNotIn('session.data(for:', section)

    def test_crypto_checks_padded_length_and_both_hashes(self):
        section = STORE.split('struct EncryptedAttachment:', 1)[1].split('struct NativeAttachmentRequest:', 1)[0]
        self.assertIn('maximumPlaintext = 8_000_000', section)
        self.assertIn('maximumCiphertext = 8_000_016', section)
        self.assertLess(section.index('ciphertext.count == paddedSize + 16'), section.index('AES.GCM.open'))
        self.assertLess(section.index('Self.digest(ciphertext) == ciphertextDigest'), section.index('AES.GCM.open'))
        self.assertIn('padded.count == paddedSize', section)
        self.assertIn('Data(padded.prefix(size))', section)
        self.assertIn('Self.digest(bytes) == sha256', section)

    def test_native_authority_and_aad_are_report_bound(self):
        section = STORE.split('struct AuthorizedAttachment:', 1)[1].split('actor ReportStore {', 1)[0]
        for fragment in ('try access.validate(reportText)', 'accounts[request.accountKey]',
                         'account["child"] as? String == request.accountKey',
                         'message["child"] as? String == request.accountKey',
                         'matches.count == 1', 'request.attachmentIndex < attachments.count',
                         'request.ref == ref', 'request.scope.principal == principal',
                         'attachment["encrypted_attachment"]', 'Set(reference.keys) == EncryptedAttachment.fields',
                         '.withoutEscapingSlashes'):
            self.assertIn(fragment, section)

    def test_bridge_reference_has_exact_protocol_fields(self):
        self.assertIn('static let fields: Set<String> = ["v", "path", "key", "iv", "sha256", "size"]', STORE)
        section = STORE.split('struct NativeAttachmentRequest:', 1)[1].split('struct AuthorizedAttachment:', 1)[0]
        self.assertIn('Set(reference.keys) == EncryptedAttachment.fields', section)

    def test_encrypted_cache_and_clear_have_revision_guard(self):
        section = STORE.split('    func attachment(', 1)[1].split('    func clear()', 1)[0]
        self.assertIn('activeAccess == access', section)
        self.assertIn('activeRevision == startedAtActiveRevision', section)
        self.assertLess(section.index('activeRevision == startedAtActiveRevision'), section.index('try protectedWrite(encrypted, to: cache)'))
        self.assertNotIn('protectedWrite(bytes', section)
        self.assertIn('"PromenadaAttachments"', STORE.split('    func clear()', 1)[1])
        self.assertIn('.completeFileProtection', STORE)
        self.assertIn('flags.isExcludedFromBackup = true', STORE)
        self.assertIn('legacy: true', STORE)

    def test_share_is_cancelled_on_logout_and_preserves_legacy(self):
        self.assertIn('let base64 = body["base64"] as? String', MODEL)
        self.assertIn('bytes.count <= EncryptedAttachment.maximumPlaintext', MODEL)
        self.assertIn('attachmentGeneration == requestAttachmentGeneration', MODEL)
        self.assertIn('self.access == access, open', MODEL)
        self.assertIn('attachmentTask?.cancel()', MODEL)
        logout = MODEL.split('    func forget()', 1)[1].split('    private func sendStatus', 1)[0]
        self.assertIn('cancelAttachmentLoad()', logout)
        self.assertIn('store.clear()', logout)
        self.assertIn('removeShare()', logout)
        self.assertIn('.completeFileProtection', MODEL)
        self.assertIn('flags.isExcludedFromBackup = true', MODEL)


if __name__ == '__main__':
    unittest.main()
