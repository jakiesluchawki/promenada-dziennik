"""Python-produced synthetic vectors must decrypt byte-for-byte in the actual JS reader."""
import base64
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import report_attachments

FIXTURES = ROOT / 'tests' / 'fixtures' / 'attachment_aad_vectors.json'


class AttachmentInterop(unittest.TestCase):
    def test_python_aad_and_padded_crypto_vectors(self):
        for vector in json.loads(FIXTURES.read_text()):
            with self.subTest(vector=vector['label']):
                report = vector['report']; child = vector['account_key']
                message = report['accounts'][child]['messages'][0]
                ref = message['attachments'][0]['encrypted_attachment']
                aad = report_attachments.aad(report, child, message, 0, ref)
                self.assertEqual(base64.b64encode(aad).decode(), vector['expected_aad_base64'])
                blob = base64.b64decode(vector['ciphertext_base64'])
                self.assertEqual(len(blob), report_attachments.padded_size(ref['size']) + 16)
                plain = report_attachments.decrypt_blob(blob, report, child, message, 0, ref)
                self.assertEqual(base64.b64encode(plain).decode(), vector['expected_plaintext_base64'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js unavailable')
    def test_actual_browser_decrypts_python_vectors_and_rejects_scope_tampering(self):
        javascript = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app.js','utf8');
const context=vm.createContext({crypto:require('node:crypto').webcrypto,TextEncoder,TextDecoder,
  Uint8Array,ArrayBuffer,AbortController,DOMException,URL,atob,btoa,console,
  localStorage:{getItem:()=>null},document:{},window:{}});
vm.runInContext(source.slice(0,source.indexOf('$("unlock-form").addEventListener'))+
  '\nglobalThis.reader={attachmentAAD,decryptAttachment,attachmentContext};',context);
(async()=>{
 for(const vector of JSON.parse(fs.readFileSync('tests/fixtures/attachment_aad_vectors.json','utf8'))){
  const report=vector.report,message=report.accounts[vector.account_key].messages[0];
  const file=message.attachments[0],ref=file.encrypted_attachment;
  const scope=context.reader.attachmentContext(report,message,0,file);
  assert.equal(Buffer.from(context.reader.attachmentAAD(ref,scope)).toString('base64'),vector.expected_aad_base64);
  const blob=Uint8Array.from(Buffer.from(vector.ciphertext_base64,'base64'));
  const plain=await context.reader.decryptAttachment(ref,scope,blob);
  assert.equal(Buffer.from(plain).toString('base64'),vector.expected_plaintext_base64);
  await assert.rejects(()=>context.reader.decryptAttachment(ref,{...scope,accountKey:'other'},blob));
  await assert.rejects(()=>context.reader.decryptAttachment(ref,{...scope,messageId:scope.messageId+'other'},blob));
  await assert.rejects(()=>context.reader.decryptAttachment(ref,{...scope,attachmentIndex:1},blob));
 }
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', javascript], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
