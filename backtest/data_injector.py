"""Historical data injector with strict anti-look-ahead guarantees."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import Any

from core.event_bus import EventBus
from core.events import BarCloseEvent, TickEvent
from data.models import OHLCVBar, Tick
from storage.data_repository import DataRepository


class WindowedDataRepository:
    """Data facade exposing only bars up to a moving visible timestamp."""

    def __init__(self, base_repository: DataRepository) -> None:
        self._base = base_repository
        self._series: dict[tuple[str, str, str], list[OHLCVBar]] = {}
        self._visible_until: dict[tuple[str, str, str], datetime | None] = {}

    async def preload_series(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Load bars once from base repository and keep in memory."""

        key = (symbol, broker, timeframe)
        if key not in self._series:
            bars = await self._base.get_ohlcv(
                symbol=symbol,
                broker=broker,
                timeframe=timeframe,
                start=start,
                end=end,
                auto_fetch=True,
            )
            self._series[key] = sorted(bars, key=lambda item: item.timestamp_close)
            self._visible_until[key] = None
        return self._series[key]

    def set_visible_until(self, symbol: str, broker: str, timeframe: str, timestamp: datetime) -> None:
        """Update visibility limit for a series."""

        key = (symbol, broker, timeframe)
        self._visible_until[key] = timestamp.astimezone(UTC)

    async def get_ohlcv(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        auto_fetch: bool = True,
    ) -> list[OHLCVBar]:
        """Return only bars up to visible timestamp to avoid look-ahead bias."""

        key = (symbol, broker, timeframe)
        if key not in self._series:
            if not auto_fetch:
                return []
            await self.preload_series(symbol, broker, timeframe, start, end)
        visible_until = self._visible_until.get(key)
        bars = self._series.get(key, [])
        filtered: list[OHLCVBar] = []
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        for bar in bars:
            if bar.timestamp_close < start_utc or bar.timestamp_close > end_utc:
                continue
            if visible_until is not None and bar.timestamp_close > visible_until:
                continue
            filtered.append(bar)
        return filtered

    def visible_count(self, symbol: str, broker: str, timeframe: str) -> int:
        """Return currently visible bars count for diagnostics/tests."""

        key = (symbol, broker, timeframe)
        bars = self._series.get(key, [])
        visible_until = self._visible_until.get(key)
        if visible_until is None:
            return 0
        return sum(1 for bar in bars if bar.timestamp_close <= visible_until)


class DataInjector:
    """Inject historical bars into EventBus one by one."""

    def __init__(
        self,
        event_bus: EventBus,
        data_repository: WindowedDataRepository,
        *,
        speed_multiplier: float = float("inf"),
        run_id: str = "backtest",
    ) -> None:
        self._event_bus = event_bus
        self._repository = data_repository
        self._speed_multiplier = speed_multiplier
        self._run_id = run_id
        self._paused = False
        self._stopped = False
        self._processed = 0
        self._total = 0

    async def inject_bars(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        warmup_bars: int = 200,
        on_bar: Callable[[OHLCVBar], Any] | None = None,
        on_progress: Callable[[int, int], Any] | None = None,
    ) -> AsyncGenerator[BarCloseEvent, None]:
        """Inject bars in chronological order and emit BAR_CLOSE after warmup."""

        bars = await self._repository.preload_series(symbol, broker, timeframe, start, end)
        self._total = len(bars)
        self._processed = 0
        self._stopped = False

        for index, bar in enumerate(bars):
            if self._stopped:
                break
            while self._paused and not self._stopped:
                await asyncio.sleep(0.01)
            if self._stopped:
                break

            self._repository.set_visible_until(symbol, broker, timeframe, bar.timestamp_close)
            self._processed = index + 1
            if on_bar is not None:
                result = on_bar(bar)
                if inspect.isawaitable(result):
                    await result
            if on_progress is not None:
                progress_result = on_progress(self._processed, self._total)
                if inspect.isawaitable(progress_result):
                    await progress_result

            if index < warmup_bars:
                continue

            tick = TickEvent(
                source="backtest.data_injector",
                run_id=self._run_id,
                symbol=bar.symbol,
                broker=bar.broker,
                bid=bar.close,
                ask=bar.close + (bar.spread or 0.0),
                last=bar.close,
                volume=bar.volume,
                timestamp=bar.timestamp_close,
            )
            await self._event_bus.publish(tick)

            event = BarCloseEvent(
                source="backtest.data_injector",
                run_id=self._run_id,
                symbol=bar.symbol,
                broker=bar.broker,
                timeframe=bar.timeframe,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                timestamp_open=bar.timestamp_open,
                timestamp_close=bar.timestamp_close,
                timestamp=bar.timestamp_close,
            )
            await self._event_bus.publish(event)
            yield event

            await self._sleep_between_bars(index, bars)

    async def inject_ticks(self, ticks: list[Tick], realtime: bool = False) -> None:
        """Inject ticks in order with optional timestamp-respecting delays."""

        ordered = sorted(ticks, key=lambda item: item.timestamp)
        previous: Tick | None = None
        for tick in ordered:
            if self._stopped:
                break
            while self._paused and not self._stopped:
                await asyncio.sleep(0.01)
            if previous is not None and realtime:
                delta = (tick.timestamp - previous.timestamp).total_seconds()
                if delta > 0:
                    await asyncio.sleep(delta / max(self._speed_multiplier, 1e-9))
            await self._event_bus.publish(
                TickEvent(
                    source="backtest.data_injector",
                    run_id=self._run_id,
                    symbol=tick.symbol,
                    broker=tick.broker,
                    bid=tick.bid,
                    ask=tick.ask,
                    last=tick.last if tick.last is not None else (tick.bid + tick.ask) / 2.0,
                    volume=tick.volume if tick.volume is not None else 0.0,
                    timestamp=tick.timestamp,
                )
            )
            previous = tick

    def get_progress(self) -> tuple[int, int]:
        """Return processed/total bars."""

        return self._processed, self._total

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._stopped = True

    async def _sleep_between_bars(self, index: int, bars: list[OHLCVBar]) -> None:
        if self._speed_multiplier == float("inf"):
            return
        if index >= len(bars) - 1:
            return
        current = bars[index].timestamp_close
        nxt = bars[index + 1].timestamp_close
        delta = max((nxt - current).total_seconds(), 0.0)
        if delta <= 0.0:
            return
        await asyncio.sleep(delta / max(self._speed_multiplier, 1e-9))


__all__ = ["DataInjector", "WindowedDataRepository"]
