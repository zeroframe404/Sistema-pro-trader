"""Base connector contract for data providers."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

from structlog.stdlib import BoundLogger

from core.config_models import BrokerConfig
from core.event_bus import EventBus
from core.events import BarCloseEvent, TickEvent
from data.models import AssetInfo, ConnectorStatus, OHLCVBar, OrderBook, Tick
from data.normalizer import Normalizer
from data.resampler import Resampler


class DataConnector(ABC):
    """Unified connector interface for brokers and market data providers."""

    connector_id: str
    broker: str
    is_paper: bool

    def __init__(
        self,
        config: BrokerConfig,
        event_bus: EventBus,
        normalizer: Normalizer,
        logger: BoundLogger,
        run_id: str,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.normalizer = normalizer
        self.log = logger.bind(connector_id=config.broker_id, broker=config.broker_type)
        self.run_id = run_id

        self.connector_id = config.broker_id
        self.broker = config.broker_type
        self.is_paper = config.paper_mode

        self._connected = False
        self._last_ping: datetime | None = None
        self._latency_ms: float | None = None
        self._error_count = 0
        self._last_error: str | None = None
        self._subscribed_symbols: set[str] = set()
        self._resampler = Resampler()

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to provider and return True on success."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect and release resources."""

    @abstractmethod
    async def ping(self) -> float:
        """Return latency in ms or raise when disconnected."""

    def is_connected(self) -> bool:
        """Return connector connectivity state."""

        return self._connected

    @abstractmethod
    async def get_available_symbols(self) -> list[AssetInfo]:
        """Return all available symbols for this connector/account."""

    @abstractmethod
    async def get_asset_info(self, symbol: str) -> AssetInfo | None:
        """Return metadata for one symbol."""

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars."""

    @abstractmethod
    async def subscribe_ticks(
        self,
        symbol: str,
        callback: Callable[[Tick], Awaitable[None]],
    ) -> None:
        """Subscribe to real-time ticks for symbol."""

    @abstractmethod
    async def unsubscribe_ticks(self, symbol: str) -> None:
        """Unsubscribe from real-time ticks for symbol."""

    async def subscribe_bars(
        self,
        symbol: str,
        timeframe: str,
        callback: Callable[[OHLCVBar], Awaitable[None]],
    ) -> None:
        """Default bar subscription built from tick stream."""

        ticks_buffer: list[Tick] = []
        published_open_times: set[datetime] = set()

        async def on_tick(tick: Tick) -> None:
            ticks_buffer.append(tick)
            bars = self._resampler.ticks_to_ohlcv(ticks=ticks_buffer, timeframe=timeframe)
            if not bars:
                return

            latest = bars[-1]
            if latest.timestamp_open in published_open_times:
                return
            if not self._resampler.is_bar_complete(latest.timestamp_open, timeframe):
                return

            published_open_times.add(latest.timestamp_open)
            await callback(latest)

        await self.subscribe_ticks(symbol=symbol, callback=on_tick)

    async def get_orderbook(self, symbol: str, depth: int = 10) -> OrderBook | None:
        """Return order book snapshot if provider supports it."""

        _ = (symbol, depth)
        return None

    def get_status(self) -> ConnectorStatus:
        """Return current connector status metadata."""

        return ConnectorStatus(
            connector_id=self.connector_id,
            broker=self.broker,
            connected=self._connected,
            last_ping=self._last_ping,
            latency_ms=self._latency_ms,
            error_count=self._error_count,
            last_error=self._last_error,
            subscribed_symbols=sorted(self._subscribed_symbols),
            is_paper=self.is_paper,
        )

    async def _publish_tick(self, tick: Tick) -> None:
        """Publish TickEvent into the core event bus."""

        last = tick.last if tick.last is not None else (tick.bid + tick.ask) / 2
        volume = tick.volume if tick.volume is not None else 0.0

        event = TickEvent(
            source=f"connector.{self.connector_id}",
            run_id=self.run_id,
            symbol=tick.symbol,
            broker=tick.broker,
            bid=tick.bid,
            ask=tick.ask,
            last=last,
            volume=volume,
            timestamp=tick.timestamp.astimezone(UTC),
        )
        await self.event_bus.publish(event)

    async def _publish_bar(self, bar: OHLCVBar) -> None:
        """Publish BarCloseEvent into the core event bus."""

        event = BarCloseEvent(
            source=f"connector.{self.connector_id}",
            run_id=self.run_id,
            symbol=bar.symbol,
            broker=bar.broker,
            timeframe=bar.timeframe,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            timestamp_open=bar.timestamp_open.astimezone(UTC),
            timestamp_close=bar.timestamp_close.astimezone(UTC),
            timestamp=bar.timestamp_close.astimezone(UTC),
        )
        await self.event_bus.publish(event)

    def _mark_connected(self, connected: bool) -> None:
        self._connected = connected

    def _record_ping(self, latency_ms: float) -> None:
        self._last_ping = datetime.now(UTC)
        self._latency_ms = latency_ms

    def _record_error(self, error: Exception | str) -> None:
        self._error_count += 1
        self._last_error = str(error)

    async def _sleep_latency(self, latency_ms: float) -> None:
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000)

    def _track_subscription(self, symbol: str, subscribe: bool) -> None:
        if subscribe:
            self._subscribed_symbols.add(symbol)
        else:
            self._subscribed_symbols.discard(symbol)

    def _safe_log_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        from data.security import redact_sensitive

        return cast(dict[str, Any], redact_sensitive(payload))
