"""CCXT execution adapter wrapper."""

from __future__ import annotations

from execution.adapters._live_stub import LiveAdapterStub

try:
    import ccxt  # type: ignore[import-not-found]  # noqa: F401

    _AVAILABLE = True
except Exception:  # noqa: BLE001
    _AVAILABLE = False


class CCXTAdapter(LiveAdapterStub):
    """CCXT adapter with availability-controlled runtime behavior."""

    _available = _AVAILABLE

    def __init__(self, run_id: str = "unknown") -> None:
        super().__init__(broker="ccxt", available=self._available, run_id=run_id)
