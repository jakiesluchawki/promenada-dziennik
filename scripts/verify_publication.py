"""Certify a fresh manifest and every referenced ciphertext blob on public Pages.

This fixed-origin check streams within existing caps and emits no private data.
"""
import hashlib, os, pathlib, sys, time, json, re
from datetime import datetime, timezone
import requests
import collector, publisher, report_attachments
from schedule_due import needs_collection
from student_run import principal_id, validate_report

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC_ROOT = 'https://jakiesluchawki.github.io/promenada-dziennik/'


def validate_fresh(report, now):
    if needs_collection(report, now):
        raise ValueError('Report is stale or an account is unhealthy')
    for account in report['accounts'].values():
        checked = datetime.fromisoformat(account.get('checked_at', report['collected_at']).replace('Z', '+00:00'))
        if checked > now: raise ValueError('Future collection timestamp')


def fetch_bounded(name, limit):
    # Callers supply only selected fixed manifest paths or validated blob paths.
    if name not in ('report.enc.json', 'report.v2.enc.json') and not (
            name.startswith('students/') and re.fullmatch(r'students/[a-f0-9]{64}(?:\.v2)?\.enc\.json', name)
            or report_attachments.BLOB_PATH.fullmatch(name)):
        raise ValueError('Invalid public path')
    url = PUBLIC_ROOT + name
    with requests.get(url, params={'verify': str(time.time_ns())},
                      headers={'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity'}, timeout=15,
                      allow_redirects=False, stream=True) as response:
        if response.status_code != 200 or response.is_redirect or response.url.split('?', 1)[0] != url:
            raise ValueError('Public ciphertext unavailable')
        advertised = response.headers.get('Content-Length')
        if advertised is not None:
            if not advertised.isdigit() or int(advertised) > limit: raise ValueError('Public ciphertext size mismatch')
        data = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if len(data) + len(chunk) > limit: raise ValueError('Public ciphertext too large')
            data.extend(chunk)
        return bytes(data)


def verify_blobs(report):
    # Verify each authenticated reference, even if two records share a path.
    for account_key, message, index, attachment in report_attachments.attachment_records(report):
        ref = attachment.get('encrypted_attachment')
        if ref is None: continue
        report_attachments.validate_reference(ref)
        data = fetch_bounded(ref['path'], report_attachments.padded_size(ref['size']) + 16)
        report_attachments.decrypt_blob(data, report, account_key, message, index, ref)


def main():
    if os.environ.get('MAHBRUS_AUDIENCE') == 'student':
        accounts = json.loads(collector.secret('student-accounts'))
        if len(accounts) != 1: raise ValueError('One student required')
        key, account = next(iter(accounts.items()))
        principal = principal_id(account['login'])
        password = account['password']
        report = publisher.load_current_report(ROOT, password, 'student', principal, key)
        validate_report(report, principal, key)
        path = publisher.current_report_path(ROOT, 'student', principal)
    else:
        password = collector.secret('site-password')
        report = publisher.load_current_report(ROOT, password, audience='parent', principal='parent')
        path = publisher.current_report_path(ROOT)
    name = path.relative_to(ROOT).as_posix()
    # Authenticate local references before attempting a success certification.
    for child, message, index, attachment in report_attachments.attachment_records(report):
        if "encrypted_attachment" in attachment:
            report_attachments.read_attachment(ROOT, report, child, message, index, attachment["encrypted_attachment"])
    validate_fresh(report, datetime.now(timezone.utc))
    payload = path.read_bytes()
    expected = hashlib.sha256(payload).digest()
    for attempt in range(4):
        try:
            remote = fetch_bounded(name, publisher.MAX_REPORT_BYTES)
            if len(remote) == len(payload) and hashlib.sha256(remote).digest() == expected:
                verify_blobs(report)
                print('Fresh healthy report and attachment ciphertext verified on Pages.'); return
        except (requests.RequestException, ValueError, publisher.ReportError):
            pass
        if attempt < 3: time.sleep(5)
    raise RuntimeError('Published ciphertext has not reached Pages')


if __name__ == '__main__':
    try: main()
    except Exception:
        print('Fresh publication could not be verified; retry is required.', file=sys.stderr)
        sys.exit(1)
