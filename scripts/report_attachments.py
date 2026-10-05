"""Authenticated, scope-bound attachment storage. Only ciphertext is public."""
import base64
import binascii
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from report_errors import ReportError

MAX_ATTACHMENT_BYTES = 8_000_000
MAX_BLOB_BYTES = MAX_ATTACHMENT_BYTES + 16
HEX = re.compile(r'[a-f0-9]{64}')
BLOB_PATH = re.compile(r'attachments/([a-f0-9]{64})\.bin')
REF_FIELDS = {'v', 'path', 'key', 'iv', 'sha256', 'size'}


def padded_size(size):
    if type(size) is not int or not 0 <= size <= MAX_ATTACHMENT_BYTES: fail()
    return min(MAX_ATTACHMENT_BYTES, max(65536, ((size + 65535) // 65536) * 65536))


def fail(code='attachment_invalid'):
    raise ReportError(code)


def decode64(value, size=None):
    try:
        if not isinstance(value, str): fail()
        raw = base64.b64decode(value, validate=True)
        if base64.b64encode(raw).decode('ascii') != value: fail()
        if size is not None and len(raw) != size: fail()
        return raw
    except (ValueError, binascii.Error):
        fail()


def validate_scope(report, audience=None, principal=None, account_key=None):
    """Validate the decrypted report before following any attachment reference."""
    if not isinstance(report, dict) or type(report.get('schema', 1)) is not int or report.get('schema', 1) not in (1, 2):
        fail('attachment_scope')
    actual_audience = report.get('audience', 'parent')
    actual_principal = report.get('principal', 'parent')
    if actual_audience not in ('parent', 'student'):
        fail('attachment_scope')
    if audience is not None and actual_audience != audience:
        fail('attachment_scope')
    if principal is not None and actual_principal != principal:
        fail('attachment_scope')
    accounts = report.get('accounts')
    if not isinstance(accounts, dict) or not accounts or any(not isinstance(k, str) or not k or not isinstance(v, dict) for k, v in accounts.items()):
        fail('attachment_scope')
    if actual_audience == 'parent':
        if actual_principal != 'parent' or any(a.get('role', 'parent') != 'parent' for a in accounts.values()):
            fail('attachment_scope')
    else:
        if not isinstance(actual_principal, str) or not HEX.fullmatch(actual_principal) or len(accounts) != 1:
            fail('attachment_scope')
        if account_key is not None and set(accounts) != {account_key}:
            fail('attachment_scope')
        if any(a.get('role') != 'student' for a in accounts.values()):
            fail('attachment_scope')
        key = next(iter(accounts))
        for kind in ('actions', 'observations'):
            if any(not isinstance(item, dict) or item.get('child') != key for item in report.get('digest', {}).get(kind, [])):
                fail('attachment_scope')
    return actual_audience, actual_principal


def attachment_records(report):
    validate_scope(report)
    for account_key, account in report['accounts'].items():
        seen_ids = set()
        for kind in ('messages', 'announcements'):
            records = account.get(kind, [])
            if not isinstance(records, list): fail('attachment_scope')
            for message in records:
                if not isinstance(message, dict): fail('attachment_scope')
                identity = message.get('id')
                if isinstance(identity, str):
                    if identity in seen_ids: fail('attachment_scope')
                    seen_ids.add(identity)
                expected_kind = 'message' if kind == 'messages' else 'announcement'
                attachments = message.get('attachments', [])
                if not isinstance(attachments, list): fail()
                for index, attachment in enumerate(attachments):
                    if not isinstance(attachment, dict): fail()
                    if 'base64' in attachment or 'encrypted_attachment' in attachment:
                        if (message.get('child') != account_key or message.get('kind') != expected_kind
                                or not isinstance(message.get('id'), str)
                                or not message['id'].startswith(account_key + ':' + expected_kind + ':')):
                            fail('attachment_scope')
                    yield account_key, message, index, attachment


def validate_reference(ref):
    if not isinstance(ref, dict) or set(ref) != REF_FIELDS or type(ref.get('v')) is not int or ref['v'] != 1:
        fail()
    if not isinstance(ref.get('path'), str) or not BLOB_PATH.fullmatch(ref['path']): fail()
    if not isinstance(ref.get('sha256'), str) or not HEX.fullmatch(ref['sha256']): fail()
    if type(ref.get('size')) is not int or not 0 <= ref['size'] <= MAX_ATTACHMENT_BYTES: fail()
    decode64(ref.get('key'), 32)
    decode64(ref.get('iv'), 12)
    return ref


def aad(report, account_key, message, index, ref):
    audience, principal = validate_scope(report)
    kind = message.get('kind')
    if (account_key not in report['accounts'] or message.get('child') != account_key or kind not in ('message', 'announcement')
            or not isinstance(message.get('id'), str) or not message['id'].startswith(account_key + ':' + kind + ':')):
        fail('attachment_scope')
    if type(index) is not int or index < 0: fail('attachment_scope')
    return json.dumps(['promenada-attachment-v1', audience, principal, account_key,
                       message['id'], index, ref['sha256'], ref['size']],
                      ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def blob_path(root, name):
    if not isinstance(name, str) or not BLOB_PATH.fullmatch(name): fail()
    root = Path(root).resolve()
    directory = root / 'attachments'
    target = root / name
    if directory.is_symlink() or target.is_symlink(): fail()
    if target.resolve().parent != directory.resolve() or directory.resolve().parent != root: fail()
    return target


def read_blob(root, ref):
    validate_reference(ref)
    target = blob_path(root, ref['path'])
    if not target.is_file(): fail('attachment_unavailable')
    try:
        with target.open('rb') as stream:
            data = stream.read(padded_size(ref['size']) + 17)
    except OSError:
        fail('attachment_unavailable')
    validate_blob(data, ref)
    return data


def validate_blob(data, ref):
    validate_reference(ref)
    if len(data) != padded_size(ref['size']) + 16 or hashlib.sha256(data).hexdigest() != BLOB_PATH.fullmatch(ref['path'])[1]:
        fail('attachment_integrity')


def decrypt_blob(data, report, account_key, message, index, ref):
    validate_blob(data, ref)
    try:
        raw = AESGCM(decode64(ref['key'], 32)).decrypt(decode64(ref['iv'], 12), data,
                                                    aad(report, account_key, message, index, ref))
    except InvalidTag:
        fail('attachment_integrity')
    if len(raw) != padded_size(ref['size']): fail('attachment_integrity')
    raw = raw[:ref['size']]
    if len(raw) != ref['size'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
        fail('attachment_integrity')
    return raw


def read_attachment(root, report, account_key, message, index, ref):
    return decrypt_blob(read_blob(root, ref), report, account_key, message, index, ref)


def write_blob(root, ref, data):
    validate_blob(data, ref)
    target = blob_path(root, ref['path'])
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        if read_blob(root, ref) != data: fail('attachment_integrity')
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.attachment-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        if read_blob(root, ref) != data: fail('attachment_integrity')
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def hydrate(report, root):
    """Restore exact bytes only in a private in-memory/temporary collection copy."""
    result = copy.deepcopy(report)
    for account_key, message, index, attachment in attachment_records(result):
        if 'encrypted_attachment' not in attachment: continue
        if result.get('schema') != 2 or attachment.get('error'): fail()
        raw = read_attachment(root, result, account_key, message, index, attachment['encrypted_attachment'])
        if 'base64' in attachment and decode64(attachment['base64']) != raw: fail('attachment_integrity')
        attachment['base64'] = base64.b64encode(raw).decode('ascii')
    return result


def externalize(report, root):
    """Write verified ciphertext first; return a manifest without inline bytes."""
    result = copy.deepcopy(report)
    result['schema'] = 2
    for account_key, message, index, attachment in attachment_records(result):
        if 'base64' not in attachment:
            if 'encrypted_attachment' in attachment:
                if attachment.get('error'): fail()
                read_attachment(root, result, account_key, message, index, attachment['encrypted_attachment'])
            continue
        if attachment.get('error'):
            # Failed records are metadata, never a route around byte validation.
            if 'encrypted_attachment' in attachment: fail()
            continue
        encoded = attachment['base64']
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_ATTACHMENT_BYTES + 2) // 3): fail('attachment_too_large')
        raw = decode64(encoded)
        if len(raw) > MAX_ATTACHMENT_BYTES: fail('attachment_too_large')
        digest = hashlib.sha256(raw).hexdigest()
        ref = attachment.get('encrypted_attachment')
        if ref is not None:
            try:
                if read_attachment(root, result, account_key, message, index, ref) != raw: ref = None
            except ReportError:
                # Inline bytes are authoritative only inside the private report;
                # invalid/moved/absent old references are never reused.
                ref = None
        if ref is None:
            ref = {'v': 1, 'path': '', 'key': base64.b64encode(secrets.token_bytes(32)).decode('ascii'),
                   'iv': base64.b64encode(secrets.token_bytes(12)).decode('ascii'), 'sha256': digest, 'size': len(raw)}
            padded = raw + secrets.token_bytes(padded_size(len(raw)) - len(raw))
            data = AESGCM(decode64(ref['key'], 32)).encrypt(decode64(ref['iv'], 12), padded,
                                                         aad(result, account_key, message, index, ref))
            ref['path'] = 'attachments/' + hashlib.sha256(data).hexdigest() + '.bin'
            write_blob(root, ref, data)
        attachment.pop('base64')
        attachment['encrypted_attachment'] = ref
    return result


def legacy_inline(report, root):
    result = hydrate(report, root) if report.get('schema') == 2 else copy.deepcopy(report)
    result['schema'] = 1
    for _, _, _, attachment in attachment_records(result):
        attachment.pop('encrypted_attachment', None)
    return result


def public_blob_files(root):
    """Strict allowlist for publishing/staging, including retained older blobs."""
    directory = Path(root) / 'attachments'
    if directory.is_symlink(): fail('unreviewed_public_file')
    if not directory.exists(): return []
    if not directory.is_dir(): fail('unreviewed_public_file')
    result = []
    for target in sorted(directory.iterdir()):
        if target.is_symlink() or not target.is_file() or not re.fullmatch(r'[a-f0-9]{64}\.bin', target.name):
            fail('unreviewed_public_file')
        with target.open('rb') as stream: data = stream.read(MAX_BLOB_BYTES + 1)
        if not 65552 <= len(data) <= MAX_BLOB_BYTES or (len(data) != MAX_BLOB_BYTES and (len(data) - 16) % 65536 != 0) or hashlib.sha256(data).hexdigest() != target.stem:
            fail('attachment_integrity')
        result.append(target)
    return result
