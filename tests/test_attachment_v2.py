"""Synthetic v2 migration/crypto/transport regressions; no live data or secrets."""
import base64
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cloud_run
import collector
import publisher
import report_attachments as blobs
import stage_site
import verify_publication
from report_errors import Diagnostics, ReportError
from student_run import principal_id
from test_report_diagnostics import previous_report, PASSWORD, MARKER


def sample(raw=b'\x00synthetic exact bytes\xff', student=False):
    report = previous_report()
    message = report['accounts']['demo']['announcements'][0]
    message['attachments'] = [{'name': 'Żółć "quoted".bin', 'mime': 'application/octet-stream',
                               'size': len(raw), 'base64': base64.b64encode(raw).decode(),
                               'custom': {'keep': True}}]
    if student:
        report.update(audience='student', principal=principal_id('synthetic student'))
        report['accounts']['demo']['role'] = 'student'
    return report


def first(report):
    return report['accounts']['demo']['announcements'][0]['attachments'][0]


class AttachmentProtocol(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_parent_exact_roundtrip_padding_metadata_and_legacy_keys(self):
        report = sample()
        original = copy.deepcopy(report)
        manifest = blobs.externalize(report, self.root)
        self.assertEqual(report, original)
        self.assertEqual(manifest['schema'], 2)
        ref = first(manifest)['encrypted_attachment']
        self.assertNotIn('base64', first(manifest))
        self.assertEqual((self.root / ref['path']).stat().st_size, 65552)
        self.assertEqual(hashlib.sha256((self.root / ref['path']).read_bytes()).hexdigest(), Path(ref['path']).stem)
        self.assertEqual(blobs.legacy_inline(manifest, self.root), report)
        hydrated = blobs.hydrate(manifest, self.root)
        self.assertEqual(first(hydrated)['base64'], first(report)['base64'])
        self.assertEqual(first(hydrated)['encrypted_attachment'], ref)

    def test_padding_boundaries_and_zero_bytes(self):
        for size, expected in [(0,65536),(1,65536),(65536,65536),(65537,131072),(7_995_392,7_995_392),(8_000_000,8_000_000)]:
            with self.subTest(size=size): self.assertEqual(blobs.padded_size(size), expected)
        manifest = blobs.externalize(sample(b''), self.root)
        self.assertEqual(first(blobs.hydrate(manifest, self.root))['base64'], '')
        for value in (True, -1, 8_000_001, 1.0):
            with self.assertRaises(ReportError): blobs.padded_size(value)

    def test_student_scope_and_same_password_parent_is_not_student(self):
        report = sample(student=True)
        manifest = blobs.externalize(report, self.root)
        self.assertEqual(blobs.legacy_inline(manifest, self.root), report)
        blobs.validate_scope(manifest, 'student', report['principal'], 'demo')
        for audience, principal, child in [('parent','parent','demo'),('student','f'*64,'demo'),('student',report['principal'],'sibling')]:
            with self.assertRaises(ReportError): blobs.validate_scope(manifest,audience,principal,child)
        mutated = copy.deepcopy(manifest)
        mutated['principal'] = 'f'*64
        with self.assertRaises(ReportError): blobs.hydrate(mutated,self.root)

    def test_reference_is_bound_to_audience_child_message_and_index(self):
        manifest = blobs.externalize(sample(), self.root)
        variants = []
        audience = copy.deepcopy(manifest)
        audience.update(audience='student', principal='a'*64)
        audience['accounts']['demo']['role'] = 'student'
        variants.append(audience)
        child = copy.deepcopy(manifest)
        child['accounts']['sibling'] = child['accounts'].pop('demo')
        child['accounts']['sibling']['announcements'][0].update(child='sibling', id='sibling:announcement:1')
        variants.append(child)
        message = copy.deepcopy(manifest)
        message['accounts']['demo']['announcements'][0]['id'] = 'demo:announcement:different'
        variants.append(message)
        index = copy.deepcopy(manifest)
        index['accounts']['demo']['announcements'][0]['attachments'].insert(0, {'name':'another','url':'https://example.invalid'})
        variants.append(index)
        for changed in variants:
            with self.subTest(changed=changed.get('audience')):
                with self.assertRaises(ReportError): blobs.hydrate(changed,self.root)
        invalid = copy.deepcopy(manifest)
        invalid['accounts']['demo']['announcements'][0]['child'] = 'sibling'
        with self.assertRaises(ReportError): blobs.hydrate(invalid,self.root)

    def test_moved_source_collection_and_duplicate_identity_are_rejected(self):
        manifest=blobs.externalize(sample(),self.root)
        changed=copy.deepcopy(manifest)
        account=changed['accounts']['demo']
        account['messages']=account['announcements'];account['announcements']=[]
        with self.assertRaises(ReportError):blobs.hydrate(changed,self.root)
        changed=copy.deepcopy(manifest)
        changed['accounts']['demo']['messages']=[copy.deepcopy(changed['accounts']['demo']['announcements'][0])]
        with self.assertRaises(ReportError):blobs.hydrate(changed,self.root)
        changed=copy.deepcopy(manifest)
        changed['accounts']['demo']['announcements'][0]['kind']='message'
        with self.assertRaises(ReportError):blobs.hydrate(changed,self.root)

    def test_reuse_requires_authentication_and_stays_stable(self):
        manifest = blobs.externalize(sample(), self.root)
        hydrated = blobs.hydrate(manifest,self.root)
        self.assertEqual(blobs.externalize(hydrated,self.root),manifest)
        self.assertEqual(len(list((self.root/'attachments').iterdir())),1)
        changed = copy.deepcopy(hydrated)
        changed['accounts']['demo']['announcements'][0]['id'] = 'demo:announcement:new'
        replacement = blobs.externalize(changed,self.root)
        self.assertNotEqual(first(replacement)['encrypted_attachment']['path'],first(manifest)['encrypted_attachment']['path'])
        self.assertEqual(first(blobs.hydrate(replacement,self.root))['base64'],first(hydrated)['base64'])

    def test_fresh_random_encryption_is_not_crossaccount_deduplication(self):
        one = blobs.externalize(sample(),self.root)
        two = blobs.externalize(sample(),self.root)
        self.assertNotEqual(first(one)['encrypted_attachment']['path'],first(two)['encrypted_attachment']['path'])
        self.assertNotEqual(first(one)['encrypted_attachment']['key'],first(two)['encrypted_attachment']['key'])

    def test_invalid_reference_or_missing_blob_replaced_only_with_inline_source(self):
        manifest = blobs.externalize(sample(),self.root)
        hydrated = blobs.hydrate(manifest,self.root)
        ref = first(manifest)['encrypted_attachment']
        (self.root/ref['path']).unlink()
        with self.assertRaises(ReportError): blobs.hydrate(manifest,self.root)
        replacement = blobs.externalize(hydrated,self.root)
        self.assertNotEqual(first(replacement)['encrypted_attachment']['path'],ref['path'])

    def test_malformed_references_and_tampering_fail_closed(self):
        manifest = blobs.externalize(sample(),self.root)
        ref = first(manifest)['encrypted_attachment']
        for key,value in [('v',True),('v',2),('size',True),('size',-1),('size',8_000_001),
                          ('path','../private.bin'),('path','https://example.invalid/blob'),('path','attachments/'+'A'*64+'.bin'),
                          ('sha256','x'*64),('key','abcd'),('iv','bad')]:
            mutated = copy.deepcopy(manifest)
            first(mutated)['encrypted_attachment'][key] = value
            with self.subTest(key=key,value=value):
                with self.assertRaises(ReportError): blobs.hydrate(mutated,self.root)
        target = self.root/ref['path']
        raw = target.read_bytes()
        for corrupted in (raw[:-1],raw+b'x',bytes([raw[0]^1])+raw[1:]):
            target.write_bytes(corrupted)
            with self.assertRaises(ReportError): blobs.hydrate(manifest,self.root)
        # Matching renamed ciphertext hash still cannot bypass GCM authentication.
        target.write_bytes(raw)
        altered = bytearray(raw);altered[-1]^=1
        new_name = 'attachments/'+hashlib.sha256(altered).hexdigest()+'.bin'
        (self.root/new_name).write_bytes(altered)
        changed=copy.deepcopy(manifest);first(changed)['encrypted_attachment']['path']=new_name
        with self.assertRaises(ReportError):blobs.hydrate(changed,self.root)

    def test_wrong_plaintext_digest_and_length_fail(self):
        # Re-encrypt a deliberately invalid reference with its own correct AAD.
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        report=blobs.externalize(sample(),self.root)
        message=report['accounts']['demo']['announcements'][0]
        ref=first(report)['encrypted_attachment']
        ref['sha256']='0'*64
        data=AESGCM(blobs.decode64(ref['key'])).encrypt(blobs.decode64(ref['iv']),b'x'*65536,blobs.aad(report,'demo',message,0,ref))
        ref['path']='attachments/'+hashlib.sha256(data).hexdigest()+'.bin'
        (self.root/ref['path']).write_bytes(data)
        with self.assertRaises(ReportError):blobs.hydrate(report,self.root)

    def test_inline_too_large_invalid_base64_and_symlinks_are_rejected(self):
        report=sample();first(report)['base64']='!invalid'
        with self.assertRaises(ReportError):blobs.externalize(report,self.root)
        first(report)['base64']='A'*(4*((8_000_000+2)//3)+4)
        with self.assertRaises(ReportError):blobs.externalize(report,self.root)
        outside=self.root/'outside';outside.mkdir()
        (self.root/'attachments').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ReportError):blobs.externalize(sample(),self.root)


class ManifestMigration(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def test_both_manifests_readable_when_inline_fits(self):
        report=sample()
        result=publisher.write_reports(report,PASSWORD,self.root)
        self.assertTrue(result['legacy_updated'])
        legacy=publisher.decrypt(json.loads((self.root/'report.enc.json').read_bytes()),PASSWORD)
        self.assertEqual(legacy,report)
        self.assertEqual(publisher.load_current_report(self.root,PASSWORD)['schema'],2)
        self.assertEqual(publisher.encrypted_payload_size(report),(self.root/'report.enc.json').stat().st_size)

    def test_real_25mb_cap_preserves_old_v1_and_all_distinct_8mb_bytes(self):
        old=json.dumps(publisher.encrypt(previous_report(),PASSWORD)).encode()
        (self.root/'report.enc.json').write_bytes(old)
        report=sample(b'x'*8_000_000)
        other=copy.deepcopy(first(report));other['name']='second.bin';other['base64']=base64.b64encode(b'y'*8_000_000).decode()
        report['accounts']['demo']['announcements'][0]['attachments'].append(other)
        result=publisher.write_reports(report,PASSWORD,self.root)
        self.assertFalse(result['legacy_updated'])
        self.assertGreater(result['legacy_encrypted_bytes'],25_000_000)
        self.assertEqual((self.root/'report.enc.json').read_bytes(),old)
        manifest=publisher.load_current_report(self.root,PASSWORD)
        self.assertLess(result['encrypted_bytes'],25_000_000)
        self.assertEqual(blobs.legacy_inline(manifest,self.root),report)
        self.assertEqual({p.stat().st_size for p in (self.root/'attachments').iterdir()},{8_000_016})

    def test_manifest_cap_and_audit_failure_preserve_existing_manifests(self):
        publisher.write_reports(sample(),PASSWORD,self.root)
        old={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        with patch.object(publisher,'MAX_REPORT_BYTES',1):
            with self.assertRaises(ReportError):publisher.write_reports(sample(),PASSWORD,self.root)
        with self.assertRaises(ReportError):
            publisher.write_reports(sample(),PASSWORD,self.root,before_write=lambda: (_ for _ in ()).throw(ReportError('plaintext_public_file')))
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},old)
        self.assertEqual(list(self.root.glob('.report-*')),[])

    def test_only_missing_v2_falls_back(self):
        report=sample()
        (self.root/'report.enc.json').write_text(json.dumps(publisher.encrypt(report,PASSWORD)))
        self.assertEqual(publisher.load_current_report(self.root,PASSWORD),report)
        target=self.root/'report.v2.enc.json'
        for payload in ('broken',json.dumps(publisher.encrypt(dict(report,schema=2),PASSWORD+'wrong')),json.dumps(publisher.encrypt(report,PASSWORD))):
            target.write_text(payload)
            with self.assertRaises(Exception):publisher.load_current_report(self.root,PASSWORD)
        target.unlink();target.symlink_to(self.root/'missing')
        with self.assertRaises(ReportError):publisher.load_current_report(self.root,PASSWORD)

    def test_student_paths_and_expected_scope_do_not_cross(self):
        student=sample(student=True);principal=student['principal']
        publisher.write_reports(student,PASSWORD,self.root)
        self.assertTrue((self.root/'students'/(principal+'.v2.enc.json')).exists())
        self.assertEqual(publisher.load_current_report(self.root,PASSWORD,'student',principal,'demo')['schema'],2)
        with self.assertRaises(ReportError):publisher.load_current_report(self.root,PASSWORD,'student',principal,'sibling')
        with self.assertRaises(ReportError):publisher.report_paths(self.root,'student','../parent')

    def test_v2_hydration_retains_archive_on_next_collection_with_stale_v1(self):
        old=json.dumps(publisher.encrypt(previous_report(),PASSWORD)).encode()
        (self.root/'report.enc.json').write_bytes(old)
        previous=sample(b'x'*10_000)
        previous['accounts']['demo']['announcements'][0].update(archived=True,original_title=MARKER,title='Archiwum · '+MARKER,last_seen_at='2026-10-01')
        with patch.object(publisher,'MAX_REPORT_BYTES',4000):publisher.write_reports(previous,PASSWORD,self.root)
        before=publisher.load_current_report(self.root,PASSWORD)
        old_ref=first(before)['encrypted_attachment']
        runner=self.root/'private';runner.mkdir()
        output=self.root/'output'
        def collect():
            state=json.loads((collector.BASE/'snapshot.json').read_text())
            self.assertEqual(first(state)['base64'],first(previous)['base64'])
            state['accounts']['demo']['announcements']=[]
            state['schema']=1
            (collector.BASE/'snapshot.json').write_text(json.dumps(state))
        secret=lambda name:PASSWORD if name=='site-password' else json.dumps({'demo':{}})
        with patch.object(cloud_run,'ROOT',self.root),patch.object(publisher,'SITE',self.root),\
             patch.object(collector,'secret',side_effect=secret),patch.object(publisher,'secret',side_effect=secret),\
             patch.object(collector,'main',side_effect=collect),patch.object(publisher,'audit'),patch('stage_site.stage'),\
             patch.object(publisher,'MAX_REPORT_BYTES',4000),patch.dict(os.environ,{'RUNNER_TEMP':str(runner),'GITHUB_OUTPUT':str(output),'PARENT_REFRESH_CONFIG':''}),\
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cloud_run.run(),0)
        self.assertEqual((self.root/'report.enc.json').read_bytes(),old)
        current=publisher.load_current_report(self.root,PASSWORD)
        source=current['accounts']['demo']['announcements'][0]
        self.assertTrue(source['archived']);self.assertEqual(source['last_seen_at'],'2026-10-01')
        self.assertEqual(first(current)['encrypted_attachment'],old_ref)
        self.assertEqual(list(runner.iterdir()),[])


class PublicOutput(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        publisher.write_reports(sample(),PASSWORD,self.root)

    def test_strict_stage_list_includes_v1_v2_and_blobs_only(self):
        paths=stage_site.encrypted_public_paths(self.root)
        names=[p.relative_to(self.root).as_posix() for p in paths]
        self.assertIn('report.enc.json',names);self.assertIn('report.v2.enc.json',names)
        self.assertEqual(sum(name.startswith('attachments/') for name in names),1)
        with patch.object(stage_site.subprocess,'run') as run:
            stage_site.stage_git(self.root)
        arguments=run.call_args.args[0]
        self.assertEqual(arguments[:5],['git','-C',str(self.root),'add','--'])
        self.assertEqual(arguments[5:],names)
        (self.root/'attachments'/'private.txt').write_text(MARKER)
        with self.assertRaises(ReportError):stage_site.encrypted_public_paths(self.root)

    def test_invalid_binary_and_student_names_are_rejected(self):
        directory=self.root/'students';directory.mkdir()
        (directory/'private.enc.json').write_text(MARKER)
        with self.assertRaises(ReportError):stage_site.encrypted_public_paths(self.root)
        (directory/'private.enc.json').unlink()
        (self.root/'attachments'/('f'*64+'.bin')).write_bytes(b'x'*65552)
        with self.assertRaises(ReportError):stage_site.encrypted_public_paths(self.root)

    def test_every_public_blob_is_authenticated_before_success(self):
        report=publisher.load_current_report(self.root,PASSWORD)
        with patch.object(verify_publication,'fetch_bounded',side_effect=lambda name,limit:(self.root/name).read_bytes()) as fetch:
            verify_publication.verify_blobs(report)
            ref=first(report)['encrypted_attachment']
            fetch.assert_called_once_with(ref['path'],65552)
        with patch.object(verify_publication,'fetch_bounded',return_value=b'wrong'):
            with self.assertRaises(ReportError):verify_publication.verify_blobs(report)

    def test_transport_is_bounded_and_denies_redirects(self):
        class Response:
            status_code=200;is_redirect=False;headers={};url=verify_publication.PUBLIC_ROOT+'report.v2.enc.json?verify=1'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def iter_content(self,chunk_size):return iter([b'12',b'345'])
        response=Response()
        with patch.object(verify_publication.requests,'get',return_value=response) as get:
            with self.assertRaises(ValueError):verify_publication.fetch_bounded('report.v2.enc.json',4)
            self.assertTrue(get.call_args.kwargs['stream']);self.assertFalse(get.call_args.kwargs['allow_redirects'])
            response.status_code=302;response.is_redirect=True
            with self.assertRaises(ValueError):verify_publication.fetch_bounded('report.v2.enc.json',100)
            with self.assertRaises(ValueError):verify_publication.fetch_bounded('../private',100)

    def test_diagnostics_reveal_only_fixed_codes(self):
        for code in ('attachment_invalid','attachment_integrity','attachment_scope','attachment_unavailable','attachment_too_large'):
            error=ReportError(code,{MARKER:100,'encrypted_bytes':12})
            self.assertEqual(Diagnostics().failure(error),'phase=initialise code='+code)


if __name__=='__main__':unittest.main()
