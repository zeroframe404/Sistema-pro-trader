"""IQ Option execution adapter wrapper."""

from __future__ import annotations

from execution.adapters._live_stub import LiveAdapterStub

try:
    import iqoptionapi  # type: ignore[import-not-found]  # noqa: F401

    _AVAILABLE = True
except Exception:  # noqa: BLE001
    _AVAILABLE = False


class IQOptionAdapter(LiveAdapterStub):
    """IQ Option adapter with availability-controlled runtime behavior."""

    _available = _AVAILABLE

    def __init__(self, run_id: str = "unknown") -> None:
        super().__init__(broker="iqoption", available=self._available, run_id=run_id)
