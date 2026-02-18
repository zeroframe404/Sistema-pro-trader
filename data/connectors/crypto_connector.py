"""CCXT-based crypto connector wrapper."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from data.base_connector import DataConnector
from data.models import AssetInfo, OHLCVBar, Tick

try:  # pragma: no cover - optional dependency
    import ccxt.async_support as ccxt_async  # type: ignore[import-not-found]

    _CCXT_AVAILABLE = True
except Exception:  # noqa: BLE001
    ccxt_async = None
    _CCXT_AVAILABLE = False


class CryptoConnector(DataConnector):
    """Multi-exchange connector powered by CCXT async support."""

    _available = _CCXT_AVAILABLE

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._exchange: Any = None

    async def connect(self) -> bool:
        if not self._available:
            self._record_error("ccxt async not available")
            self._mark_connected(False)
            return False

        exchange_name = str(self.config.extra.get("exchange", "binance"))
        exchange_class = getattr(ccxt_async, exchange_name, None)
        if exchange_class is None:
            self._record_error(f"unsupported exchange: {exchange_name}")
            self._mark_connected(False)
            return False

        self._exchange = exchange_class(
            {
                "apiKey": str(self.config.extra.get("api_key", "")),
                "secret": str(self.config.extra.get("secret", "")),
                "enableRateLimit": True,
            }
        )

        if bool(self.config.extra.get("sandbox", False)):
            self._exchange.set_sandbox_mode(True)

        await self._exchange.load_markets()
        await self._exchange.fetch_time()
        self._mark_connected(True)
        return True

    async def disconnect(self) -> None:
        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception:  # noqa: BLE001
                pass
        self._mark_connected(False)

    async def ping(self) -> float:
        if not self.is_connected():
            raise RuntimeError("Crypto connector not connected")
        start = datetime.now(UTC)
        await self._exchange.fetch_time()
        latency = (datetime.now(UTC) - start).total_seconds() * 1000
        self._record_ping(latency)
        return latency

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
        _ = end
        if not self.is_connected():
            return []

        since_ms = int(start.astimezone(UTC).timestamp() * 1000)
        rows = await self._exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe.lower(), since=since_ms, limit=limit)
        normalized_symbol = self.normalizer.normalize_symbol(self.broker, symbol)
        bars: list[OHLCVBar] = []
        for row in rows:
            bars.append(self.normalizer.normalize_ohlcv_ccxt(row, symbol=normalized_symbol, broker=self.broker))
        return bars

    async def subscribe_ticks(self, symbol: str, callback: Callable[[Tick], Awaitable[None]]) -> None:
        _ = callback
        self._track_subscription(symbol, True)

    async def unsubscribe_ticks(self, symbol: str) -> None:
        self._track_subscription(symbol, False)
