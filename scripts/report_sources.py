"""Preserve only authenticated historical sources needed by parent actions."""
import copy
from report_errors import ReportError

ARCHIVE_PREFIX = 'Archiwum · '


def documents(account):
    return account.get('messages', []) + account.get('announcements', [])


def reconcile_sources(previous, current, digest):
    """Never invent a source, cross an account boundary, or retain unrelated notices.

    The caller supplies the decrypted prior parent snapshot. Current Librus
    content wins. A missing announcement may be retained only when it is still
    the evidence for an existing action; its original content remains intact.
    """
    result = copy.deepcopy(current)
    accounts = result['accounts']
    for action in digest.get('actions', []):
        source_id = action.get('source_id')
        if not source_id:
            continue
        child = action.get('child')
        if child not in accounts:
            raise ReportError('digest_source_scope')
        account = accounts[child]
        if any(item.get('id') == source_id for key, other in accounts.items() if key != child for item in documents(other)):
            raise ReportError('digest_source_scope')
        matches = [item for item in documents(account) if item.get('id') == source_id]
        if matches:
            if len(matches) != 1 or matches[0].get('child') != child:
                raise ReportError('digest_source_scope')
            continue
        old_account = previous.get('accounts', {}).get(child, {})
        candidates = [item for item in old_account.get('announcements', []) if item.get('id') == source_id]
        if len(candidates) != 1 or account.get('status') != 'ok':
            raise ReportError('digest_unknown_source')
        source = candidates[0]
        if (source.get('child') != child or source.get('kind') != 'announcement'
                or not isinstance(source_id, str) or not source_id.startswith(child + ':announcement:')):
            raise ReportError('digest_source_scope')
        archived = copy.deepcopy(source)
        original_title = source.get('original_title') if source.get('archived') is True else source.get('title')
        if not isinstance(original_title, str):
            raise ReportError('digest_unknown_source')
        archived.update(archived=True, original_title=original_title, title=ARCHIVE_PREFIX + original_title)
        # Preserve the first last-seen time instead of making archived evidence
        # appear freshly observed on every successful refresh.
        if not source.get('archived'):
            archived['last_seen_at'] = old_account.get('checked_at', previous.get('collected_at'))
        account.setdefault('announcements', []).append(archived)
    return result
