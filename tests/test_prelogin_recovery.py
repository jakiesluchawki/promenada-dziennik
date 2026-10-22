"""Synthetic failures only; recovery must never replay ambiguous authentication."""
import contextlib
import copy
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import requests
import collector
import publisher
import student_run
from librus_http import PreLoginUnavailable, failure_code, prelogin_retryable

PRIVATE = "SYNTHETIC_PRIVATE_FAILURE"
ACCOUNTS = {"demo": {"login": "synthetic", "password": PRIVATE, "expected": "Demo"}}


class PreLoginClassification(unittest.TestCase):
    def test_initial_timeout_is_classified_before_credentials_and_session_is_closed(self):
        session = Mock(headers={})
        with patch.object(collector, "secret", return_value=json.dumps(ACCOUNTS)), \
             patch.object(collector.requests, "Session", return_value=session), \
             patch.object(collector, "request", side_effect=requests.ConnectTimeout(PRIVATE)) as request:
            with self.assertRaises(PreLoginUnavailable) as raised:
                collector.login("demo")
        self.assertEqual(failure_code(raised.exception), "network_timeout")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[1], "GET")
        self.assertNotIn("data", request.call_args.kwargs)
        session.close.assert_called_once()

    def test_tls_and_access_denials_do_not_become_retryable(self):
        forbidden = Mock(status_code=403)
        for error in [requests.exceptions.SSLError(PRIVATE), requests.HTTPError(PRIVATE, response=forbidden)]:
            with self.subTest(error=type(error).__name__), \
                 patch.object(collector, "secret", return_value=json.dumps(ACCOUNTS)), \
                 patch.object(collector.requests, "Session", return_value=Mock(headers={})), \
                 patch.object(collector, "request", side_effect=error):
                with self.assertRaises(type(error)):
                    collector.login("demo")

    def test_timeout_after_credentials_is_not_classified_as_prelogin(self):
        landing = Mock(url="https://api.librus.pl/OAuth/Authorization")
        captcha = Mock()
        captcha.json.return_value = {"is_needed": False}
        with patch.object(collector, "secret", return_value=json.dumps(ACCOUNTS)), \
             patch.object(collector.requests, "Session", return_value=Mock(headers={})), \
             patch.object(collector, "request", side_effect=[landing, captcha, requests.ReadTimeout(PRIVATE)]) as request:
            with self.assertRaises(requests.ReadTimeout):
                collector.login("demo")
        self.assertEqual([c.args[1] for c in request.call_args_list], ["GET", "POST", "POST"])

    def test_only_all_prelogin_transient_failures_allow_one_new_runner(self):
        error = {"status": "error", "error_phase": "pre_login", "error_code": "network_timeout"}
        self.assertTrue(prelogin_retryable({"accounts": {"a": error, "b": {"status": "ok"}}}))
        for changed in [{"error_phase": None}, {"error_code": "tls_error"}, {"error_code": "collection_failed"}]:
            with self.subTest(changed=changed):
                self.assertFalse(prelogin_retryable({"accounts": {"a": error, "b": error | changed}}))
        self.assertFalse(prelogin_retryable({"accounts": {}}))
        self.assertFalse(prelogin_retryable({"accounts": {"a": {"status": "ok"}}}))


class PreservedAccountRecovery(unittest.TestCase):
    def run_collector(self, previous, collect, since=""):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(collector, "BASE", pathlib.Path(temporary)), \
             patch.object(collector, "secret", return_value=json.dumps({k: {} for k in previous["accounts"]})), \
             patch.object(collector, "collect_account", side_effect=collect) as call, \
             patch.dict(os.environ, {"MAHBRUS_RECOVERY_SINCE": since}), \
             contextlib.redirect_stdout(io.StringIO()):
            target = pathlib.Path(temporary) / "snapshot.json"
            target.write_text(json.dumps(previous))
            try:
                collector.main()
            except SystemExit as error:
                self.assertEqual(error.code, 2)
            return json.loads(target.read_text()), call.call_args_list

    def test_prelogin_error_retains_checked_at_and_private_data(self):
        old = {"status": "ok", "checked_at": "2026-10-20T04:30:00+00:00", "messages": [{"text": PRIVATE}]}
        result, _ = self.run_collector({"accounts": {"demo": old}}, PreLoginUnavailable(requests.ConnectTimeout(PRIVATE)))
        account = result["accounts"]["demo"]
        self.assertEqual(account["checked_at"], old["checked_at"])
        self.assertEqual(account["messages"], old["messages"])
        self.assertEqual(account["error_phase"], "pre_login")
        self.assertTrue(prelogin_retryable(result))

    def test_later_failure_clears_old_prelogin_classification(self):
        old = {"status": "error", "error_phase": "pre_login", "error_code": "network_timeout"}
        result, _ = self.run_collector({"accounts": {"demo": old}}, requests.ReadTimeout(PRIVATE))
        self.assertNotIn("error_phase", result["accounts"]["demo"])
        self.assertFalse(prelogin_retryable(result))

    def test_new_runner_skips_only_accounts_completed_in_the_first_attempt(self):
        now = datetime.now(timezone.utc)
        since = (now - timedelta(minutes=2)).isoformat()
        checked = (now - timedelta(minutes=1)).isoformat()
        previous = {"accounts": {
            "done": {"status": "ok", "checked_at": checked, "messages": [{"text": PRIVATE}]},
            "failed": {"status": "error", "checked_at": "2026-10-20T04:30:00+00:00"},
            "old": {"status": "ok", "checked_at": "2026-10-20T04:30:00+00:00"},
        }}
        def collect(key, old):
            return {"status": "ok", "checked_at": now.isoformat(), "messages": [], "announcements": [], "sections": {}}
        result, calls = self.run_collector(previous, collect, since)
        self.assertEqual([c.args[0] for c in calls], ["failed", "old"])
        self.assertEqual(result["accounts"]["done"], previous["accounts"]["done"])


class StudentRecoveryMetadata(unittest.TestCase):
    def test_student_failure_exports_only_retry_classification_and_preserves_ciphertext(self):
        principal = student_run.principal_id("synthetic")
        previous = {"schema": 1, "audience": "student", "principal": principal,
                    "collected_at": "2026-10-20T04:30:00+00:00", "digest": {},
                    "accounts": {"demo": {"role": "student", "status": "ok", "messages": [], "sections": {}}}}
        failed = copy.deepcopy(previous)
        failed["accounts"]["demo"].update(status="error", error=PRIVATE, error_code="network_timeout", error_phase="pre_login")
        accounts = copy.deepcopy(ACCOUNTS)
        accounts["demo"]["role"] = "student"
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            target = root / "ciphertext"
            target.write_bytes(b"unchanged synthetic ciphertext")
            output = root / "github-output"
            with patch.object(student_run, "ROOT", root), \
                 patch.object(collector, "secret", return_value=json.dumps(accounts)), \
                 patch.object(publisher, "secret", collector.secret), \
                 patch.object(publisher, "current_report_path", return_value=target), \
                 patch.object(publisher, "load_current_report", return_value=previous), \
                 patch.object(collector, "main"), patch.object(publisher, "load_report", return_value=failed), \
                 patch.dict(os.environ, {"GITHUB_OUTPUT": str(output), "MAHBRUS_SCHEDULED": "false"}):
                with self.assertRaisesRegex(RuntimeError, "Student collection incomplete"):
                    student_run.main()
            self.assertEqual(target.read_bytes(), b"unchanged synthetic ciphertext")
            self.assertEqual(output.read_text(), "due=true\nretryable=true\nrecovery_since=2026-10-20T04:30:00+00:00\n")
            self.assertNotIn(PRIVATE, output.read_text())


if __name__ == "__main__":
    unittest.main()
