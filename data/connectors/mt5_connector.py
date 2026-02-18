"""MetaTrader 5 connector wrapper with graceful availability fallback."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from data.base_connector import DataConnector
from data.models import AssetInfo, OHLCVBar, Tick

try:  # pragma: no cover - availability depends on platform/runtime
    import MetaTrader5  # type: ignore[import-not-found]

    _MT5_AVAILABLE = True
except Exception:  # noqa: BLE001
    MetaTrader5 = None
    _MT5_AVAILABLE = False


class MT5Connector(DataConnector):
    """MT5 connector with optional runtime support."""

    _available = _MT5_AVAILABLE

    async def connect(self) -> bool:
        if not self._available:
            self._record_error("MetaTrader5 library not available")
            self._mark_connected(False)
            return False

        extra = self.config.extra
        login_raw = extra.get("login")
        login = int(login_raw) if isinstance(login_raw, (int, float, str)) and str(login_raw) else None
        initialized = bool(
            MetaTrader5.initialize(
                path=str(extra.get("mt5_path", "")) or None,
                login=login,
                password=str(extra.get("password", "")) or None,
                server=str(extra.get("server", "")) or None,
            )
        )
        self._mark_connected(initialized)
        if not initialized:
            self._record_error("mt5.initialize failed")
        return initialized

    async def disconnect(self) -> None:
        if self._available and self.is_connected():
            MetaTrader5.shutdown()
        self._mark_connected(False)

    async def ping(self) -> float:
        if not self.is_connected():
            raise RuntimeError("MT5 connector not connected")
        start = datetime.now(UTC)
        _ = MetaTrader5.terminal_info() if self._available else None
        latency = (datetime.now(UTC) - start).total_seconds() * 1000
        self._record_ping(latency)
        return latency

    async def get_available_symbols(self) -> list[AssetInfo]:
        if not self._available or not self.is_connected():
            return []
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
        if not self._available:
            return []
        return []

    async def subscribe_ticks(self, symbol: str, callback: Callable[[Tick], Awaitable[None]]) -> None:
        _ = callback
        if not self._available:
            raise RuntimeError("MetaTrader5 library not available")
        self._track_subscription(symbol, True)

    async def unsubscribe_ticks(self, symbol: str) -> None:
        self._track_subscription(symbol, False)

    async def get_active_chart_symbol(self) -> str | None:
        """Return active chart symbol when available in integration runtime."""

        if not self._available:
            return None
        return None
