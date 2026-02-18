from __future__ import annotations

from data.security import redact_sensitive


def test_redact_sensitive_values() -> None:
    payload = {
        "username": "user",
        "password": "secret",
        "nested": {"api_key": "abc", "safe": "ok"},
    }

    redacted = redact_sensitive(payload)

    assert redacted["password"] == "***REDACTED***"
    assert redacted["nested"]["api_key"] == "***REDACTED***"
    assert redacted["nested"]["safe"] == "ok"
