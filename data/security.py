"""Sensitive data redaction helpers for logging."""

from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {
    "password",
    "secret",
    "api_key",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "login",
}


def redact_sensitive(value: Any) -> Any:
    """Recursively redact sensitive values from nested structures."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted

    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)

    return value
