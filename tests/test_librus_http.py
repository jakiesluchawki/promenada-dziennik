"""Synthetic transport failures; no Librus access or real credentials."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import collector
from librus_http import failure_code, request

PRIVATE = "SYNTHETIC_PRIVATE_URL_AND_TOKEN"
URL = "https://synergia.librus.pl/synthetic"


def response(status=200):
    return Mock(status_code=status)


class BoundedTransport(unittest.TestCase):
    def test_timeout_then_connection_failure_then_success(self):
        session = Mock()
        success = response()
        session.request.side_effect = [requests.ConnectTimeout(PRIVATE), requests.ConnectionError(PRIVATE), success]
        with patch("librus_http.time.sleep") as sleep:
            self.assertIs(request(session, "GET", URL, headers={"Accept": "text/html"}), success)
        self.assertEqual(session.request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5])
        self.assertEqual(session.request.call_args.kwargs["timeout"], (5, 30))
        self.assertEqual(session.request.call_args.kwargs["headers"], {"Accept": "text/html"})

    def test_persistent_timeout_stops_after_three_attempts(self):
        session = Mock()
        session.request.side_effect = requests.ConnectTimeout(PRIVATE)
        with patch("librus_http.time.sleep") as sleep, self.assertRaises(requests.ConnectTimeout):
            request(session, "GET", URL)
        self.assertEqual(session.request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_unavailable_read_retries_and_closes_failed_responses(self):
        session = Mock()
        bad_gateway, unavailable, success = response(502), response(503), response()
        session.request.side_effect = [bad_gateway, unavailable, success]
        with patch("librus_http.time.sleep"):
            self.assertIs(request(session, "GET", URL), success)
        bad_gateway.close.assert_called_once()
        unavailable.close.assert_called_once()
        success.close.assert_not_called()

    def test_persistent_unavailability_returns_last_failure_to_caller(self):
        session = Mock()
        responses = [response(504) for _ in range(3)]
        session.request.side_effect = responses
        with patch("librus_http.time.sleep"):
            self.assertIs(request(session, "GET", URL), responses[-1])
        self.assertEqual(session.request.call_count, 3)
        responses[-1].close.assert_not_called()

    def test_authentication_post_is_never_replayed(self):
        session = Mock()
        session.request.side_effect = requests.ReadTimeout(PRIVATE)
        with patch("librus_http.time.sleep") as sleep, self.assertRaises(requests.ReadTimeout):
            request(session, "POST", URL, data={"synthetic": "value"})
        session.request.assert_called_once()
        self.assertEqual(session.request.call_args.kwargs["timeout"], 30)
        sleep.assert_not_called()
        session.request.side_effect = None
        session.request.return_value = response(503)
        session.request.reset_mock()
        request(session, "POST", URL)
        session.request.assert_called_once()

    def test_access_denials_and_rate_limits_are_not_retried(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                session = Mock()
                session.request.return_value = response(status)
                with patch("librus_http.time.sleep") as sleep:
                    self.assertEqual(request(session, "GET", URL).status_code, status)
                session.request.assert_called_once()
                sleep.assert_not_called()

    def test_tls_failure_is_not_retried_or_weakened(self):
        session = Mock()
        session.request.side_effect = requests.exceptions.SSLError(PRIVATE)
        with patch("librus_http.time.sleep") as sleep, self.assertRaises(requests.exceptions.SSLError):
            request(session, "GET", URL)
        session.request.assert_called_once()
        self.assertNotIn("verify", session.request.call_args.kwargs)
        sleep.assert_not_called()

    def test_success_needs_one_request_and_preserves_attachment_timeout(self):
        session = Mock()
        session.request.return_value = response()
        with patch("librus_http.time.sleep") as sleep:
            request(session, "GET", URL, timeout=45, params={"synthetic": "value"})
        session.request.assert_called_once()
        self.assertEqual(session.request.call_args.kwargs["timeout"], (5, 45))
        sleep.assert_not_called()

    def test_diagnostic_labels_do_not_include_private_exception_details(self):
        for error, code in [(requests.ConnectTimeout(PRIVATE), "network_timeout"),
                            (requests.ReadTimeout(PRIVATE), "network_timeout"),
                            (requests.ConnectionError(PRIVATE), "network_connection"),
                            (requests.exceptions.SSLError(PRIVATE), "tls_error"),
                            (RuntimeError(PRIVATE), "collection_failed"),
                            (requests.HTTPError(PRIVATE, response=response(503)), "upstream_unavailable")]:
            with self.subTest(code=code):
                self.assertEqual(failure_code(error), code)
                self.assertNotIn(PRIVATE, failure_code(error))


class PreservedSnapshot(unittest.TestCase):
    def test_exhausted_request_keeps_last_good_account_timestamp_and_data(self):
        previous = {"collected_at": "2026-10-12T04:30:00+00:00", "accounts": {
            "demo": {"status": "ok", "checked_at": "2026-10-12T04:30:00+00:00",
                     "messages": [{"id": "demo:message:1", "text": PRIVATE}], "sections": {}},
        }}
        with tempfile.TemporaryDirectory() as temporary, patch.object(collector, "BASE", pathlib.Path(temporary)), \
             patch.object(collector, "secret", return_value=json.dumps({"demo": {}})), \
             patch.object(collector, "collect_account", side_effect=requests.ConnectTimeout(PRIVATE)), \
             contextlib.redirect_stdout(io.StringIO()):
            target = pathlib.Path(temporary) / "snapshot.json"
            target.write_text(json.dumps(previous))
            with self.assertRaises(SystemExit) as raised:
                collector.main()
            result = json.loads(target.read_text())
        self.assertEqual(raised.exception.code, 2)
        account = result["accounts"]["demo"]
        self.assertEqual(account["status"], "error")
        self.assertEqual(account["error_code"], "network_timeout")
        self.assertEqual(account["checked_at"], previous["accounts"]["demo"]["checked_at"])
        self.assertEqual(account["messages"], previous["accounts"]["demo"]["messages"])


if __name__ == "__main__":
    unittest.main()
