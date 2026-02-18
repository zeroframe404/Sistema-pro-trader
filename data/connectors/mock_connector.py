"""Mock data connector for development and tests."""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from structlog.stdlib import BoundLogger

from core.config_models import BrokerConfig
from core.event_bus import EventBus
from data.asset_types import AssetClass, AssetMarket
from data.base_connector import DataConnector
from data.models import AssetInfo, OHLCVBar, Tick
from data.normalizer import Normalizer


class MockConnector(DataConnector):
    """Simulated connector with injectable data and controllable latency/errors."""

    _available = True

    def __init__(
        self,
        config: BrokerConfig,
        event_bus: EventBus,
        normalizer: Normalizer,
        logger: BoundLogger,
        run_id: str,
        ohlcv_data: dict[str, list[OHLCVBar]] | None = None,
        tick_data: dict[str, list[Tick]] | None = None,
        latency_ms: float = 10.0,
        error_rate: float = 0.0,
    ) -> None:
        super().__init__(
            config=config,
            event_bus=event_bus,
            normalizer=normalizer,
            logger=logger,
            run_id=run_id,
        )
        self._ohlcv_data = ohlcv_data or {}
        self._tick_data = tick_data or {}
        self._simulated_latency_ms = latency_ms
        self._error_rate = error_rate
        self._tick_callbacks: dict[str, list[Callable[[Tick], Awaitable[None]]]] = {}
        self._bar_callbacks: dict[tuple[str, str], list[Callable[[OHLCVBar], Awaitable[None]]]] = {}

    async def connect(self) -> bool:
        await self._sleep_latency(self._simulated_latency_ms)
        self._maybe_raise_error()
        self._mark_connected(True)
        return True

    async def disconnect(self) -> None:
        await self._sleep_latency(self._simulated_latency_ms)
        self._mark_connected(False)

    async def ping(self) -> float:
        if not self.is_connected():
            raise RuntimeError("mock connector is disconnected")
        await self._sleep_latency(self._simulated_latency_ms)
        latency = self._simulated_latency_ms
        self._record_ping(latency)
        return latency

    async def get_available_symbols(self) -> list[AssetInfo]:
        symbols = set(self._ohlcv_data) | set(self._tick_data)
        result: list[AssetInfo] = []
        for symbol in sorted(symbols):
            asset_class = self.normalizer.detect_asset_class(self.broker, symbol, {})
            result.append(
                AssetInfo(
                    symbol=symbol,
                    broker=self.broker,
                    name=symbol,
                    asset_class=asset_class,
                    market=AssetMarket.UNKNOWN,
                    currency="USD",
                    base_currency=symbol[:3] if len(symbol) >= 6 else None,
                    quote_currency=symbol[3:6] if len(symbol) >= 6 else None,
                    contract_size=1.0,
                    min_volume=0.01,
                    max_volume=1000000,
                    volume_step=0.01,
                    pip_size=0.0001,
                    digits=5,
                    trading_hours={},
                    available_timeframes=["M1", "M5", "H1", "D1"],
                    supported_order_types=["MARKET", "LIMIT"],
                    extra={},
                )
            )
        return result

    async def get_asset_info(self, symbol: str) -> AssetInfo | None:
        for asset in await self.get_available_symbols():
            if asset.symbol == symbol:
                return asset
        return None

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[OHLCVBar]:
        self._maybe_raise_error()
        await self._sleep_latency(self._simulated_latency_ms)

        bars = self._ohlcv_data.get(symbol, [])
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC) if end is not None else None

        filtered = [
            item
            for item in bars
            if item.timeframe == timeframe
            and item.timestamp_open >= start_utc
            and (end_utc is None or item.timestamp_open <= end_utc)
        ]

        if limit is not None:
            filtered = filtered[-limit:]

        return filtered

    async def subscribe_ticks(self, symbol: str, callback: Callable[[Tick], Awaitable[None]]) -> None:
        self._maybe_raise_error()
        self._track_subscription(symbol, True)
        self._tick_callbacks.setdefault(symbol, []).append(callback)

    async def unsubscribe_ticks(self, symbol: str) -> None:
        self._track_subscription(symbol, False)
        self._tick_callbacks.pop(symbol, None)

    async def subscribe_bars(
        self,
        symbol: str,
        timeframe: str,
        callback: Callable[[OHLCVBar], Awaitable[None]],
    ) -> None:
        self._bar_callbacks.setdefault((symbol, timeframe), []).append(callback)

    async def load_from_parquet(self, path: Path, symbol: str) -> None:
        try:
            import polars as pl
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("polars is required to load parquet in MockConnector") from exc

        frame = pl.read_parquet(path)
        bars: list[OHLCVBar] = []
        for row in frame.to_dicts():
            bars.append(
                OHLCVBar(
                    symbol=symbol,
                    broker=self.broker,
                    timeframe=str(row.get("timeframe", "M1")),
                    timestamp_open=self._parse_dt(row.get("timestamp_open")),
                    timestamp_close=self._parse_dt(row.get("timestamp_close")),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0.0)),
                    tick_count=int(row["tick_count"]) if row.get("tick_count") is not None else None,
                    spread=float(row["spread"]) if row.get("spread") is not None else None,
                    asset_class=AssetClass(str(row.get("asset_class", "unknown"))),
                    source=str(row.get("source", "mock")),
                )
            )
        self._ohlcv_data[symbol] = sorted(bars, key=lambda item: item.timestamp_open)

    async def load_from_csv(self, path: Path, symbol: str) -> None:
        try:
            import polars as pl
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("polars is required to load csv in MockConnector") from exc

        frame = pl.read_csv(path)
        bars: list[OHLCVBar] = []
        for row in frame.to_dicts():
            bars.append(
                OHLCVBar(
                    symbol=symbol,
                    broker=self.broker,
                    timeframe=str(row.get("timeframe", "M1")),
                    timestamp_open=self._parse_dt(row.get("timestamp_open")),
                    timestamp_close=self._parse_dt(row.get("timestamp_close")),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0.0)),
                    tick_count=int(row["tick_count"]) if row.get("tick_count") is not None else None,
                    spread=float(row["spread"]) if row.get("spread") is not None else None,
                    asset_class=AssetClass(str(row.get("asset_class", "unknown"))),
                    source=str(row.get("source", "mock")),
                )
            )
        self._ohlcv_data[symbol] = sorted(bars, key=lambda item: item.timestamp_open)

    async def inject_tick(self, tick: Tick) -> None:
        """Inject one tick and dispatch callbacks/event bus."""

        self._tick_data.setdefault(tick.symbol, []).append(tick)
        callbacks = self._tick_callbacks.get(tick.symbol, [])
        for callback in callbacks:
            await callback(tick)
        await self._publish_tick(tick)

    async def inject_bar(self, bar: OHLCVBar) -> None:
        """Inject one OHLCV bar and dispatch callbacks/event bus."""

        self._ohlcv_data.setdefault(bar.symbol, []).append(bar)
        callbacks = self._bar_callbacks.get((bar.symbol, bar.timeframe), [])
        for callback in callbacks:
            await callback(bar)
        await self._publish_bar(bar)

    def _maybe_raise_error(self) -> None:
        if self._error_rate <= 0:
            return
        if random.random() < self._error_rate:
            error = RuntimeError("MockConnector injected error")
            self._record_error(error)
            raise error

    @staticmethod
    def _parse_dt(value: object) -> datetime:
        if isinstance(value, datetime):
            return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        raise TypeError(f"Unsupported datetime value: {value!r}")
