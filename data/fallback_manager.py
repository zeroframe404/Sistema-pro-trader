"""Automatic fallback routing across connectors."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from data.base_connector import DataConnector
from data.models import OHLCVBar, Tick


class FallbackManager:
    """Manage connector priority and failover per symbol."""

    def __init__(self, connectors: list[DataConnector]) -> None:
        self._connectors: dict[str, DataConnector] = {item.connector_id: item for item in connectors}
        self._priority_by_symbol: dict[str, list[str]] = {}
        self._active_source: dict[str, str] = {}

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
    ) -> list[OHLCVBar]:
        """Try connectors by priority and return first successful non-empty result."""

        last_error: Exception | None = None
        for connector in self._ordered_connectors(symbol):
            try:
                bars = await connector.get_ohlcv(symbol=symbol, timeframe=timeframe, start=start, end=end)
                if bars:
                    self._active_source[symbol] = connector.connector_id
                    return bars
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        return []

    async def subscribe_ticks(
        self,
        symbol: str,
        callback: Callable[[Tick], Awaitable[None]],
    ) -> None:
        """Subscribe using the highest-priority connector available."""

        last_error: Exception | None = None
        for connector in self._ordered_connectors(symbol):
            try:
                await connector.subscribe_ticks(symbol=symbol, callback=callback)
                self._active_source[symbol] = connector.connector_id
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"No connectors available for symbol {symbol}")

    def set_priority(self, symbol: str, connector_ids: list[str]) -> None:
        """Set explicit connector priority for a symbol."""

        self._priority_by_symbol[symbol] = connector_ids

    def get_active_source(self, symbol: str) -> str:
        """Return active connector id for symbol."""

        return self._active_source.get(symbol, "")

    def _ordered_connectors(self, symbol: str) -> list[DataConnector]:
        configured = self._priority_by_symbol.get(symbol)
        if configured:
            ordered = [self._connectors[item] for item in configured if item in self._connectors]
            if ordered:
                return ordered
        return list(self._connectors.values())
