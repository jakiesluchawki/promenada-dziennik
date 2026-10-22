"""Bounded retries for transient read failures; authentication is never replayed."""
import time

import requests

RETRY_DELAYS = (2, 5)
CONNECT_TIMEOUT = 5
RETRY_STATUSES = frozenset({502, 503, 504})
FAILURE_CODES = frozenset({
    "network_timeout", "network_connection", "tls_error", "upstream_unavailable", "collection_failed",
})
TRANSIENT_CODES = frozenset({"network_timeout", "network_connection", "upstream_unavailable"})


class PreLoginUnavailable(RuntimeError):
    """A transient failure of the initial GET, before any credentials were sent."""
    def __init__(self, error):
        self.error_code = failure_code(error)
        if self.error_code not in TRANSIENT_CODES:
            raise ValueError("Not a transient pre-login failure")
        super().__init__(str(error))


def prelogin_retryable(snapshot):
    failed = [a for a in snapshot.get("accounts", {}).values() if a.get("status") != "ok"]
    return bool(failed) and all(a.get("error_phase") == "pre_login" and
                                a.get("error_code") in TRANSIENT_CODES for a in failed)


def failure_code(error):
    """Content-free labels suitable for public CI diagnostics."""
    if isinstance(error, PreLoginUnavailable):
        return error.error_code
    if isinstance(error, requests.exceptions.SSLError):
        return "tls_error"
    if isinstance(error, requests.exceptions.Timeout):
        return "network_timeout"
    if isinstance(error, requests.exceptions.ConnectionError):
        return "network_connection"
    if isinstance(error, requests.exceptions.HTTPError):
        response = error.response
        if response is not None and response.status_code in RETRY_STATUSES:
            return "upstream_unavailable"
    return "collection_failed"


def request(session, method, url, *, timeout=30, **kwargs):
    """At most three GET/HEAD attempts, with unchanged TLS and access checks.

    A shorter connection timeout bounds each address attempt; the response-read
    timeout stays unchanged. POSTs, 401/403/429, and TLS failures are not retried.
    Existing callers remain responsible for their destination/identity checks.
    """
    method = method.upper()
    retryable = method in {"GET", "HEAD"}
    attempts = len(RETRY_DELAYS) + 1 if retryable else 1
    timeouts = (min(CONNECT_TIMEOUT, timeout), timeout) if retryable else timeout
    for attempt in range(attempts):
        try:
            response = session.request(method, url, timeout=timeouts, **kwargs)
        except requests.exceptions.SSLError:
            raise
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == attempts - 1:
                raise
        else:
            if response.status_code not in RETRY_STATUSES or attempt == attempts - 1:
                return response
            response.close()
        time.sleep(RETRY_DELAYS[attempt])
