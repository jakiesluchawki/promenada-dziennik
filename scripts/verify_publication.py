"""Certify fresh, healthy account data AND identical ciphertext on public Pages.

Runs inside GitHub with report credentials. Logs no plaintext or credentials;
Netlify only reads this step's success/failure via Actions metadata.
"""
import hashlib, json, os, pathlib, sys, time
from datetime import datetime, timezone
import requests
import collector, publisher
from schedule_due import needs_collection
from student_run import principal_id, validate_report

ROOT = pathlib.Path(__file__).resolve().parent.parent

def validate_fresh(report, now):
    if needs_collection(report, now):
        raise ValueError('Report is stale or an account is unhealthy')
    for account in report['accounts'].values():
        checked = datetime.fromisoformat(account.get('checked_at', report['collected_at']).replace('Z', '+00:00'))
        if checked > now: raise ValueError('Future collection timestamp')

def main():
    if os.environ.get('MAHBRUS_AUDIENCE') == 'student':
        accounts = json.loads(collector.secret('student-accounts'))
        if len(accounts) != 1: raise ValueError('One student required')
        key, account = next(iter(accounts.items()))
        principal = principal_id(account['login'])
        name, password = 'students/' + principal + '.enc.json', account['password']
    else:
        name, password = 'report.enc.json', collector.secret('site-password')
    payload = (ROOT / name).read_bytes()
    report = publisher.decrypt(json.loads(payload), password)
    if os.environ.get('MAHBRUS_AUDIENCE') == 'student': validate_report(report, principal, key)
    validate_fresh(report, datetime.now(timezone.utc))
    expected = hashlib.sha256(payload).digest()
    for attempt in range(4):
        try:
            response = requests.get('https://jakiesluchawki.github.io/promenada-dziennik/' + name,
                params={'verify': str(time.time_ns())}, headers={'Cache-Control': 'no-cache'}, timeout=15, allow_redirects=False)
            if response.status_code == 200 and hashlib.sha256(response.content).digest() == expected:
                print('Fresh healthy report verified on Pages.'); return
        except requests.RequestException: pass
        if attempt < 3: time.sleep(5)
    raise RuntimeError('Published ciphertext has not reached Pages')

if __name__ == '__main__':
    try: main()
    except Exception:
        print('Fresh publication could not be verified; retry is required.', file=sys.stderr)
        sys.exit(1)
