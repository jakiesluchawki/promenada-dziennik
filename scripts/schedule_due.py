#!/usr/bin/env python3
"""Retry a missed morning/evening collection, without collecting twice in a slot."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json, os, pathlib
import collector, publisher
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

def main():
    report_path = pathlib.Path(__file__).resolve().parent.parent / "report.enc.json"
    report = publisher.decrypt(json.loads(report_path.read_text()), collector.secret("site-password"))
    now = datetime.now(ZONE)
    checked = datetime.fromisoformat(report["collected_at"].replace("Z", "+00:00"))
    due = (now - checked).total_seconds() >= 300
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" or os.environ.get("MAHBRUS_SCHEDULED") == "true":
        due = due and needs_collection(report, now)
    with open(os.environ["GITHUB_OUTPUT"], "a") as out: out.write("due="+str(due).lower()+"\n")
    print("Collection is due." if due else "This collection window already has a healthy report; no Librus login needed.")

if __name__ == "__main__": main()
