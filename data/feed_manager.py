"""Data feed orchestration across connectors and storage."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from structlog.stdlib import BoundLogger

from core.event_bus import EventBus
from core.logger import get_logger
from data.base_connector import DataConnector
from data.fallback_manager import FallbackManager
from data.models import ConnectorStatus, OHLCVBar, Tick
from storage.cache_manager import CacheManager
from storage.data_repository import DataRepository
from storage.parquet_store import ParquetStore
from storage.sqlite_store import SQLiteStore


class FeedManager:
    """Lifecycle and data orchestration for all active data connectors."""

    def __init__(
        self,
        connectors: list[DataConnector],
        event_bus: EventBus,
        run_id: str,
        data_store_path: Path,
        logger: BoundLogger | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._run_id = run_id
        self._connectors: dict[str, DataConnector] = {item.connector_id: item for item in connectors}
        self._logger = logger or get_logger("data.feed_manager")

        parquet_store = ParquetStore(base_path=data_store_path)
        sqlite_store = SQLiteStore(db_path=data_store_path / "metadata.sqlite")
        cache_manager = CacheManager()
        fallback_manager = FallbackManager(connectors=list(self._connectors.values()))

        self._repository = DataRepository(
            parquet_store=parquet_store,
            sqlite_store=sqlite_store,
            cache_manager=cache_manager,
            connectors={item.broker: item for item in connectors},
            fallback_manager=fallback_manager,
        )
        self._sqlite_store = sqlite_store
        self._fallback_manager = fallback_manager
        self._running = False

    async def start(self) -> None:
        """Initialize stores and connect active connectors."""

        if self._running:
            return

        await self._sqlite_store.initialize()
        results = await asyncio.gather(
            *(connector.connect() for connector in self._connectors.values()),
            return_exceptions=True,
        )
        for connector, result in zip(self._connectors.values(), results, strict=False):
            if isinstance(result, Exception):
                self._logger.warning(
                    "connector_connect_failed",
                    connector_id=connector.connector_id,
                    error=str(result),
                )
            else:
                self._logger.info(
                    "connector_connect_result",
                    connector_id=connector.connector_id,
                    connected=bool(result),
                )

        self._running = True

    async def stop(self) -> None:
        """Disconnect all connectors cleanly."""

        if not self._running:
            return

        await asyncio.gather(
            *(connector.disconnect() for connector in self._connectors.values()),
            return_exceptions=True,
        )
        self._running = False

    async def add_connector(self, connector: DataConnector) -> None:
        """Add and connect a connector at runtime."""

        self._connectors[connector.connector_id] = connector
        await connector.connect()

    async def remove_connector(self, connector_id: str) -> None:
        """Disconnect and remove connector by id."""

        connector = self._connectors.pop(connector_id, None)
        if connector is not None:
            await connector.disconnect()

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        preferred_broker: str | None = None,
    ) -> list[OHLCVBar]:
        """Route OHLCV retrieval through cache/storage with connector fallback."""

        end_dt = end or datetime.now(tz=start.tzinfo)

        if preferred_broker is not None:
            return await self._repository.get_ohlcv(
                symbol=symbol,
                broker=preferred_broker,
                timeframe=timeframe,
                start=start,
                end=end_dt,
                auto_fetch=True,
            )

        for connector in self._connectors.values():
            bars = await self._repository.get_ohlcv(
                symbol=symbol,
                broker=connector.broker,
                timeframe=timeframe,
                start=start,
                end=end_dt,
                auto_fetch=True,
            )
            if bars:
                return bars

        return []

    async def subscribe(
        self,
        symbol: str,
        timeframe: str | None = None,
        callback: Callable[[OHLCVBar], Awaitable[None]] | None = None,
    ) -> None:
        """Subscribe symbol ticks or bars through the best available connector."""

        if not self._connectors:
            raise RuntimeError("No connectors available")

        connector = next(iter(self._connectors.values()))

        if timeframe is None:
            async def default_tick_callback(_tick: Tick) -> None:
                return None

            await self._fallback_manager.subscribe_ticks(symbol, callback=default_tick_callback)
            return

        if callback is None:

            async def default_bar_callback(_bar: OHLCVBar) -> None:
                return None

            await connector.subscribe_bars(symbol=symbol, timeframe=timeframe, callback=default_bar_callback)
            return

        await connector.subscribe_bars(symbol=symbol, timeframe=timeframe, callback=callback)

    def get_connector_status(self) -> list[ConnectorStatus]:
        """Return status for all managed connectors."""

        return [connector.get_status() for connector in self._connectors.values()]

    async def health_check(self) -> dict[str, bool]:
        """Ping connectors and return aliveness map."""

        results: dict[str, bool] = {}
        for connector in self._connectors.values():
            try:
                await connector.ping()
                results[connector.connector_id] = True
            except Exception:  # noqa: BLE001
                results[connector.connector_id] = False
        return results

    def get_repository(self) -> DataRepository:
        """Expose the shared data repository for analytical modules."""

        return self._repository
