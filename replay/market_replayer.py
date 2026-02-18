"""Historical market replay runtime."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from core.event_bus import EventBus
from core.events import BarCloseEvent, TickEvent
from data.models import OHLCVBar
from execution.order_manager import OrderManager
from replay.replay_controller import ReplayController
from risk.risk_manager import RiskManager
from signals.signal_engine import SignalEngine
from storage.data_repository import DataRepository


class MarketReplayer:
    """Replay historical bars at controlled speed into the live event bus."""

    def __init__(
        self,
        data_repository: DataRepository,
        event_bus: EventBus,
        signal_engine: SignalEngine,
        risk_manager: RiskManager,
        order_manager: OrderManager,
        controller: ReplayController,
        run_id: str = "replay",
    ) -> None:
        self._repository = data_repository
        self._event_bus = event_bus
        self._signal_engine = signal_engine
        self._risk_manager = risk_manager
        self._order_manager = order_manager
        self._controller = controller
        self._run_id = run_id
        self._bars: list[OHLCVBar] = []
        self._index = 0
        self._context: dict[str, Any] = {}
        self._task: asyncio.Task[None] | None = None

    async def start(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        speed: float = 1.0,
    ) -> None:
        """Start replay loop and publish bars to event bus."""

        self._bars = await self._repository.get_ohlcv(
            symbol=symbol,
            broker=broker,
            timeframe=timeframe,
            start=start,
            end=end,
            auto_fetch=True,
        )
        self._bars.sort(key=lambda item: item.timestamp_close)
        self._index = 0
        self._context = {
            "symbol": symbol,
            "broker": broker,
            "timeframe": timeframe,
            "start": start.astimezone(UTC),
            "end": end.astimezone(UTC),
        }
        self._controller.set_speed(speed)
        self._controller.mark_running()

        async def _loop() -> None:
            while self._index < len(self._bars) and self._controller.state != ReplayController.State.FINISHED:
                bar = self._bars[self._index]
                await self._emit_bar(bar)
                self._index += 1
                interval = self._bar_interval_seconds(self._index - 1)
                await self._controller.wait_for_next_bar(interval)
            self._controller.mark_idle()

        self._task = asyncio.create_task(_loop(), name="market-replayer")
        await self._task
        await self._event_bus.drain(timeout_seconds=2.0)

    async def step_forward(self, n_bars: int = 1) -> BarCloseEvent | None:
        """Step forward N bars and emit latest bar event."""

        if not self._bars:
            return None
        self._controller.pause()
        latest: BarCloseEvent | None = None
        for _ in range(max(n_bars, 0)):
            if self._index >= len(self._bars):
                break
            latest = await self._emit_bar(self._bars[self._index])
            self._index += 1
        return latest

    async def step_backward(self, n_bars: int = 1) -> BarCloseEvent | None:
        """Move replay cursor backward without emitting historical undo events."""

        if not self._bars:
            return None
        self._controller.pause()
        self._index = max(self._index - max(n_bars, 0), 0)
        if self._index >= len(self._bars):
            return None
        bar = self._bars[self._index]
        return BarCloseEvent(
            source="replay.market_replayer",
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

    async def jump_to(self, target_datetime: datetime) -> None:
        """Move replay cursor to first bar after target timestamp."""

        if not self._bars:
            return
        target = target_datetime.astimezone(UTC)
        self._index = 0
        for idx, bar in enumerate(self._bars):
            if bar.timestamp_close >= target:
                self._index = idx
                break

    def get_current_state(self) -> dict[str, Any]:
        """Return current replay runtime state."""

        return {
            "state": self._controller.state.value,
            "speed": self._controller.current_speed,
            "index": self._index,
            "total_bars": len(self._bars),
            "context": self._context,
            "open_positions": len(self._order_manager.get_open_positions()),
            "active_signals": len(self._signal_engine.get_active_signals()),
            "risk_report": self._risk_manager.get_risk_report().model_dump(mode="python"),
        }

    async def _emit_bar(self, bar: OHLCVBar) -> BarCloseEvent:
        await self._event_bus.publish(
            TickEvent(
                source="replay.market_replayer",
                run_id=self._run_id,
                symbol=bar.symbol,
                broker=bar.broker,
                bid=bar.close,
                ask=bar.close + (bar.spread or 0.0),
                last=bar.close,
                volume=bar.volume,
                timestamp=bar.timestamp_close,
            )
        )
        event = BarCloseEvent(
            source="replay.market_replayer",
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
        return event

    def _bar_interval_seconds(self, index: int) -> float:
        if index >= len(self._bars) - 1:
            return 0.0
        current = self._bars[index].timestamp_close
        nxt = self._bars[index + 1].timestamp_close
        return max((nxt - current).total_seconds(), 0.0)


__all__ = ["MarketReplayer"]
