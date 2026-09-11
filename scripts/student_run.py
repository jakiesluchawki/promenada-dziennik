#!/usr/bin/env python3
"""Collect one verified student principal; never open the family report or digest."""
import contextlib, hashlib, io, json, os, pathlib, sys, tempfile
from datetime import datetime, timezone
import collector, publisher
from schedule_due import needs_collection
ROOT = pathlib.Path(__file__).resolve().parent.parent

def principal_id(login):
    return hashlib.sha256(login.strip().lower().encode()).hexdigest()

def validate_report(report, principal, key):
    if report.get('audience') != 'student' or report.get('principal') != principal or set(report.get('accounts', {})) != {key}:
        raise ValueError('Student report audience mismatch')
    for account in report['accounts'].values():
        if account.get('role') != 'student': raise ValueError('Student role missing')
    for kind in ('actions', 'observations'):
        if any(item.get('child') != key for item in report.get('digest', {}).get(kind, [])):
            raise ValueError('Foreign digest entry')

def main():
    accounts_raw = collector.secret('student-accounts')
    accounts = json.loads(accounts_raw)
    if len(accounts) != 1: raise ValueError('Exactly one student account required')
    key, info = next(iter(accounts.items()))
    if info.get('role') != 'student': raise ValueError('Student credentials required')
    principal = principal_id(info['login'])
    target = ROOT / 'students' / (principal + '.enc.json')
    password = info['password']
    previous = None
    if target.exists():
        previous = publisher.decrypt(json.loads(target.read_text()), password)
        validate_report(previous, principal, key)
    if '--dry-run' not in sys.argv and previous:
        checked = datetime.fromisoformat(previous['collected_at'].replace('Z', '+00:00'))
        if (datetime.now(timezone.utc) - checked).total_seconds() < 300:
            output('due', 'false'); print('Recent student report retained; cooldown active.'); return
        if (os.environ.get('GITHUB_EVENT_NAME') == 'schedule' or os.environ.get('MAHBRUS_SCHEDULED') == 'true') and not needs_collection(previous, datetime.now(timezone.utc)):
            output('due', 'false'); print('Student collection window already covered.'); return
    output('due', 'true')
    original_secret = collector.secret
    def scoped_secret(name):
        if name == 'accounts': return accounts_raw
        if name == 'site-password': return password
        return original_secret(name)
    collector.secret = publisher.secret = scoped_secret
    try:
        with tempfile.TemporaryDirectory(prefix='mahbrus-student-', dir=os.environ.get('RUNNER_TEMP')) as temporary:
            collector.BASE = publisher.BASE = pathlib.Path(temporary)
            if previous:
                # This snapshot is explicitly student-only; no parent fallback or parent digest.
                (collector.BASE/'snapshot.json').write_text(json.dumps(previous, ensure_ascii=False))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                if '--dry-run' not in sys.argv:
                    try: collector.main()
                    except SystemExit: pass
                elif not previous: raise ValueError('No student snapshot for dry run')
                report = publisher.load_report()
            if any(a.get('status') != 'ok' for a in report['accounts'].values()):
                raise RuntimeError('Student collection incomplete; previous ciphertext preserved')
            report.update(audience='student', principal=principal)
            for account in report['accounts'].values(): account['role'] = 'student'
            refresh = os.environ.get('STUDENT_REFRESH_CONFIG')
            if refresh: report['refresh'] = json.loads(refresh)
            elif previous and previous.get('refresh'): report['refresh'] = previous['refresh']
            validate_report(report, principal, key)
            envelope = publisher.encrypt(report, password)
            validate_report(publisher.decrypt(envelope, password), principal, key)
            target.parent.mkdir(exist_ok=True)
            temporary_path = target.with_suffix('.tmp')
            temporary_path.write_text(json.dumps(envelope, separators=(',', ':')))
            temporary_path.replace(target)
            print(json.dumps({'student_report': True, 'messages': len(report['accounts'][key].get('messages', [])), 'sections': list(report['accounts'][key].get('sections', {}))}))
    finally:
        collector.secret = publisher.secret = original_secret
    from stage_site import stage
    stage(ROOT)
    output('healthy', 'true')

def output(key, value):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f: f.write(key+'='+value+'\n')

if __name__ == '__main__':
    try: main()
    except Exception:
        print('Student refresh failed. The existing student report was preserved; no family data substituted.', file=sys.stderr)
        sys.exit(1)
