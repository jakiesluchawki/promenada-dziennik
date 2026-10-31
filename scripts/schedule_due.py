#!/usr/bin/env python3
"""Retry a missed morning/evening collection, without collecting twice in a slot."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json, os, pathlib
import collector, publisher
from librus_http import prelogin_retryable
ZONE = ZoneInfo("Europe/Warsaw")

def slot_start(now):
    now = now.astimezone(ZONE)
    if now.hour >= 18: return now.replace(hour=18, minute=0, second=0, microsecond=0)
    if (now.hour, now.minute) >= (6, 30): return now.replace(hour=6, minute=30, second=0, microsecond=0)
    return (now-timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)

def needs_collection(report, now):
    slot = slot_start(now)
    accounts = report.get("accounts", {})
    if not accounts: return True
    for account in accounts.values():
        if account.get("status") != "ok": return True
        try:
            checked = datetime.fromisoformat(account.get("checked_at", report["collected_at"]).replace("Z", "+00:00"))
            if checked.tzinfo is None or checked < slot: return True
        except (ValueError, KeyError, TypeError): return True
    return False

def collection_plan(report, now, *, scheduled, recovery_since=None):
    """Return whether to collect, which successful reads to reuse, and the reason."""
    collected = datetime.fromisoformat(report["collected_at"].replace("Z", "+00:00"))
    if collected.tzinfo is None or collected > now:
        raise ValueError("Invalid collection timestamp")
    if scheduled and not needs_collection(report, now):
        return False, "", "This collection window already has a healthy report; no Librus login needed."

    if recovery_since:
        # Only the second job of this same failed pre-login attempt may bypass cooldown.
        if datetime.fromisoformat(recovery_since) != collected or not prelogin_retryable(report):
            raise ValueError("Recovery does not match the failed report")
    elif now - collected < timedelta(minutes=5):
        return False, "", "Recent collection attempt; cooldown active."

    # A scheduled retry only needs the missing accounts in the current Warsaw slot.
    # A manual refresh can reuse a successful read only from its own first job.
    reuse_since = collected.isoformat() if recovery_since else ""
    if scheduled:
        reuse_since = slot_start(now).isoformat()
    return True, reuse_since, "Collection is due."

def main():
    root = pathlib.Path(__file__).resolve().parent.parent
    report = publisher.load_current_report(root, collector.secret("site-password"), audience="parent", principal="parent")
    now = datetime.now(ZONE)
    scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule" or os.environ.get("MAHBRUS_SCHEDULED") == "true"
    due, reuse_since, message = collection_plan(
        report, now, scheduled=scheduled, recovery_since=os.environ.get("MAHBRUS_RECOVERY_SINCE"),
    )
    with open(os.environ["GITHUB_OUTPUT"], "a") as out:
        out.write(f"due={str(due).lower()}\nreuse_since={reuse_since}\n")
    print(message)

if __name__ == "__main__":
    try: main()
    except Exception:
        import sys
        print("Collection window could not be checked safely.", file=sys.stderr)
        sys.exit(1)
