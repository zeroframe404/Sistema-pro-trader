"""TradingView connector placeholder."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from data.base_connector import DataConnector
from data.models import AssetInfo, OHLCVBar, Tick


class TradingViewConnector(DataConnector):
    """Placeholder connector for TradingView webhook/tvdatafeed integration."""

    _available = False

    async def connect(self) -> bool:
        self._mark_connected(False)
        self._record_error("TradingView connector requires custom webhook integration")
        return False

    async def disconnect(self) -> None:
        self._mark_connected(False)

    async def ping(self) -> float:
        raise RuntimeError("TradingView connector unavailable")

    async def get_available_symbols(self) -> list[AssetInfo]:
        return []

    async def get_asset_info(self, symbol: str) -> AssetInfo | None:
        _ = symbol
        return None

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[OHLCVBar]:
        _ = (symbol, timeframe, start, end, limit)
        return []

    async def subscribe_ticks(self, symbol: str, callback: Callable[[Tick], Awaitable[None]]) -> None:
        _ = (symbol, callback)
        raise RuntimeError("TradingView connector unavailable")

    async def unsubscribe_ticks(self, symbol: str) -> None:
        _ = symbol
