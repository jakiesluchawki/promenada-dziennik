#!/usr/bin/env python3
"""One-shot, read-only size check of an existing encrypted report.

Never collect school data, write a report, upload an artifact or print content.
Only SITE_PASSWORD is needed; account credentials are deliberately unnecessary.
"""
import copy
import json
import os
import pathlib
import sys

import publisher
from report_errors import Diagnostics


def measure(path):
    original = path.read_bytes()
    report = publisher.decrypt(json.loads(original), os.environ['SITE_PASSWORD'])
    candidate = copy.deepcopy(report)
    removed = 0
    for account in candidate['accounts'].values():
        for kind in ('messages', 'announcements'):
            for message in account.get(kind, []):
                if 'attachments' not in message:
                    continue
                previous = message['attachments']
                message['attachments'] = publisher.unique_attachments(previous)
                removed += len(previous) - len(message['attachments'])
    # The v1 salt/nonce/tag and JSON envelope overhead are fixed size.
    envelope = publisher.encrypt(candidate, os.environ['SITE_PASSWORD'])
    candidate_bytes = len(json.dumps(envelope, separators=(',', ':')).encode())
    return {
        'existing_encrypted_bytes': len(original),
        'candidate_encrypted_bytes': candidate_bytes,
        'saved_encrypted_bytes': len(original) - candidate_bytes,
        'removed_exact_attachment_duplicates': removed,
        'existing_plaintext_bytes': len(publisher.canonical(report)),
        'candidate_plaintext_bytes': len(publisher.canonical(candidate)),
        'existing_attachment_bytes': publisher.report_size_metrics(report, len(original))['attachment_bytes'],
        'candidate_attachment_bytes': publisher.report_size_metrics(candidate, candidate_bytes)['attachment_bytes'],
        'limit_bytes': publisher.MAX_REPORT_BYTES,
        'candidate_within_limit': candidate_bytes <= publisher.MAX_REPORT_BYTES,
        'fresh_collection_performed': False,
        'report_written': False,
    }


def main():
    try:
        result = measure(pathlib.Path(__file__).resolve().parents[1] / 'report.enc.json')
    except Exception as error:
        print('Read-only size measurement failed. ' + Diagnostics().failure(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
