"""Unified repository facade across cache, parquet, and connectors."""

from __future__ import annotations

from datetime import datetime

from data.base_connector import DataConnector
from data.fallback_manager import FallbackManager
from data.models import AssetInfo, OHLCVBar
from data.resampler import Resampler
from storage.cache_manager import CacheManager
from storage.parquet_store import ParquetStore
from storage.sqlite_store import SQLiteStore


class DataRepository:
    """Single entry point for historical data access."""

    def __init__(
        self,
        parquet_store: ParquetStore,
        sqlite_store: SQLiteStore,
        cache_manager: CacheManager,
        connectors: dict[str, DataConnector] | None = None,
        fallback_manager: FallbackManager | None = None,
    ) -> None:
        self._parquet_store = parquet_store
        self._sqlite_store = sqlite_store
        self._cache = cache_manager
        self._connectors = connectors or {}
        self._fallback = fallback_manager
        self._resampler = Resampler()

    async def get_ohlcv(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        auto_fetch: bool = True,
    ) -> list[OHLCVBar]:
        """Get OHLCV bars from cache/parquet and optionally fetch missing data."""

        cache_key = self._cache.make_ohlcv_key(symbol=symbol, broker=broker, timeframe=timeframe, start=start, end=end)
        cached = await self._cache.get_ohlcv(cache_key)
        if cached is not None:
            return cached

        stored = await self._parquet_store.load_bars(
            symbol=symbol,
            broker=broker,
            timeframe=timeframe,
            start=start,
            end=end,
        )
        if stored:
            await self._cache.set_ohlcv(cache_key, stored)
            return stored

        if not auto_fetch:
            return []

        bars: list[OHLCVBar] = []
        connector = self._connectors.get(broker)
        if connector is not None:
            try:
                bars = await connector.get_ohlcv(symbol=symbol, timeframe=timeframe, start=start, end=end)
            except Exception:  # noqa: BLE001
                if self._fallback is not None:
                    bars = await self._fallback.get_ohlcv(
                        symbol=symbol,
                        timeframe=timeframe,
                        start=start,
                        end=end,
                    )
                else:
                    raise
        elif self._fallback is not None:
            bars = await self._fallback.get_ohlcv(symbol=symbol, timeframe=timeframe, start=start, end=end)

        if bars:
            await self.save_ohlcv(bars)
            await self._cache.set_ohlcv(cache_key, bars)

        return bars

    async def save_ohlcv(self, bars: list[OHLCVBar]) -> None:
        """Persist OHLCV bars into parquet storage."""

        await self._parquet_store.save_bars(bars)

    async def get_asset_info(self, symbol: str, broker: str) -> AssetInfo | None:
        """Return asset metadata from SQLite store."""

        return await self._sqlite_store.get_asset_info(symbol=symbol, broker=broker)

    async def list_available_data(self) -> list[dict[str, str]]:
        """List currently stored parquet partitions."""

        results: list[dict[str, str]] = []
        root = self._parquet_store._base_path  # noqa: SLF001
        for file_path in sorted(root.rglob("*.parquet")):
            parts = file_path.relative_to(root).parts
            if len(parts) < 4:
                continue
            results.append(
                {
                    "broker": parts[0],
                    "symbol": parts[1],
                    "timeframe": parts[2],
                    "partition": file_path.name,
                }
            )
        return results

    async def get_data_gaps(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, str | int]]:
        """Detect timestamp gaps in stored bar series."""

        bars = await self._parquet_store.load_bars(
            symbol=symbol,
            broker=broker,
            timeframe=timeframe,
            start=start,
            end=end,
        )
        if not bars:
            return []

        expected = self._resampler.get_timeframe_seconds(timeframe)
        gaps: list[dict[str, str | int]] = []

        ordered = sorted(bars, key=lambda item: item.timestamp_open)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            delta = int((current.timestamp_open - previous.timestamp_open).total_seconds())
            if delta <= expected:
                continue
            missing = (delta // expected) - 1
            gaps.append(
                {
                    "from": previous.timestamp_open.isoformat(),
                    "to": current.timestamp_open.isoformat(),
                    "missing_bars": missing,
                }
            )

        return gaps
