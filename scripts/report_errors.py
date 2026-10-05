"""Allowlisted diagnostics for public CI logs; never serialize private exceptions."""
import json
from cryptography.exceptions import InvalidTag

ERROR_CODES = frozenset({
    "digest_unknown_source", "digest_source_scope", "unreviewed_public_file", "plaintext_public_file", "report_too_large",
    "attachment_invalid", "attachment_scope", "attachment_too_large", "attachment_unavailable", "attachment_integrity",
})
PHASES = frozenset({
    "initialise", "prepare_workspace", "decrypt_previous", "prepare_snapshot",
    "collect", "reconcile_sources", "load_report", "encrypt_report", "verify_encryption", "write_ciphertext", "audit_public_files",
    "prepare_state", "check_collection", "stage_site", "write_health", "cleanup",
    "externalize_attachments", "hydrate_attachments",
})


class ReportError(RuntimeError):
    def __init__(self, code, metrics=None):
        self.code = code if code in ERROR_CODES else "unexpected_error"
        # Only fixed, content-free counters may enter public diagnostics.
        self.metrics = {key: value for key, value in (metrics or {}).items()
                        if self.code == "report_too_large"
                        and key in {"encrypted_bytes", "plaintext_bytes", "attachment_bytes"}
                        and type(value) is int and 0 <= value <= 10**12}
        super().__init__(self.code)


def error_code(error):
    if isinstance(error, ReportError):
        return error.code if error.code in ERROR_CODES else "unexpected_error"
    for kind, code in (
        (InvalidTag, "decryption_failed"),
        (json.JSONDecodeError, "invalid_json"),
        (KeyError, "missing_field"),
        (TypeError, "invalid_type"),
        (ValueError, "invalid_value"),
        (AssertionError, "integrity_check_failed"),
        (OSError, "filesystem_error"),
    ):
        if isinstance(error, kind):
            return code
    return "unexpected_error"


class Diagnostics:
    def __init__(self):
        self.phase = "initialise"

    def set_phase(self, phase):
        self.phase = phase if phase in PHASES else "initialise"

    def failure(self, error):
        result = f"phase={self.phase} code={error_code(error)}"
        if isinstance(error, ReportError):
            result += "".join(f" {key}={value}" for key, value in sorted(error.metrics.items()))
        return result
