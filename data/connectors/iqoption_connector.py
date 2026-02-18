"""IQ Option connector wrapper with graceful dependency handling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from data.base_connector import DataConnector
from data.models import AssetInfo, OHLCVBar, Tick

try:  # pragma: no cover - optional dependency
    from iqoptionapi.stable_api import IQ_Option  # type: ignore[import-not-found]

    _IQ_AVAILABLE = True
except Exception:  # noqa: BLE001
    IQ_Option = None
    _IQ_AVAILABLE = False


class IQOptionConnector(DataConnector):
    """IQ Option data connector wrapper."""

    _available = _IQ_AVAILABLE

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client: Any = None

    async def connect(self) -> bool:
        if not self._available:
            self._record_error("iqoptionapi not available")
            self._mark_connected(False)
            return False

        extra = self.config.extra
        email = str(extra.get("email", ""))
        password = str(extra.get("password", ""))
        self._client = IQ_Option(email, password)
        ok, _reason = self._client.connect()
        self._mark_connected(bool(ok))
        if not ok:
            self._record_error("IQ Option connect failed")
        return bool(ok)

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.close_connect()
            except Exception:  # noqa: BLE001
                pass
        self._mark_connected(False)

    async def ping(self) -> float:
        if not self.is_connected():
            raise RuntimeError("IQ Option connector not connected")
        start = datetime.now(UTC)
        _ = self._client.get_balance() if self._client is not None else None
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
        _ = (symbol, timeframe, start, end, limit)
        return []

    async def subscribe_ticks(self, symbol: str, callback: Callable[[Tick], Awaitable[None]]) -> None:
        _ = callback
        if not self._available:
            raise RuntimeError("iqoptionapi not available")
        self._track_subscription(symbol, True)

    async def unsubscribe_ticks(self, symbol: str) -> None:
        self._track_subscription(symbol, False)

    async def get_available_timeframes_for_binary(self, symbol: str) -> list[str]:
        """Return common binary option expiries/timeframes."""

        _ = symbol
        return ["M1", "M5", "M15"]
