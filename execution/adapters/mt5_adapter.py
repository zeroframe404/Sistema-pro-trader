"""MetaTrader 5 execution adapter wrapper."""

from __future__ import annotations

import importlib.util

from execution.adapters._live_stub import LiveAdapterStub

_AVAILABLE = importlib.util.find_spec("MetaTrader5") is not None


class MT5Adapter(LiveAdapterStub):
    """MT5 adapter with availability-controlled runtime behavior."""

    _available = _AVAILABLE

    def __init__(self, run_id: str = "unknown") -> None:
        super().__init__(broker="mt5", available=self._available, run_id=run_id)
