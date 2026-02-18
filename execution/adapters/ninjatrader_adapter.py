"""NinjaTrader execution adapter wrapper."""

from __future__ import annotations

from execution.adapters._live_stub import LiveAdapterStub


class NinjaTraderAdapter(LiveAdapterStub):
    """NinjaTrader adapter placeholder with explicit unavailable state."""

    _available = False

    def __init__(self, run_id: str = "unknown") -> None:
        super().__init__(broker="ninjatrader", available=self._available, run_id=run_id)
