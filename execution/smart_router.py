"""Execution venue selection helper."""

from __future__ import annotations

from typing import Any


class SmartRouter:
    """Select broker adapter by broker id and health/latency."""

    def __init__(self, adapters: dict[str, Any], fallback_adapter: Any) -> None:
        self._adapters = adapters
        self._fallback = fallback_adapter

    async def route(self, broker: str) -> Any:
        """Return preferred adapter for broker with health-aware fallback."""

        candidate = self._adapters.get(broker)
        if candidate is None:
            return self._fallback
        try:
            if hasattr(candidate, "is_connected") and not candidate.is_connected():
                return self._fallback
            if hasattr(candidate, "ping"):
                latency = await candidate.ping()
                if latency > 5_000:
                    return self._fallback
            return candidate
        except Exception:  # noqa: BLE001
            return self._fallback

    def register_adapter(self, broker: str, adapter: Any) -> None:
        """Register or update adapter for broker key."""

        self._adapters[broker] = adapter
