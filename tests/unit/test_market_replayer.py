from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.event_types import EventType
from core.events import BarCloseEvent, BaseEvent
from replay.market_replayer import MarketReplayer
from replay.replay_controller import ReplayController


@pytest.mark.asyncio
async def test_start_injects_bars_chronologically(tmp_path: Path) -> None:
    run_id = "test-replay-start"
    (
        event_bus,
        repository,
        _indicator_engine,
        _regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path)
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=20)
        bars = generate_synthetic_bars(symbol="EURUSD", broker="mock_dev", timeframe="H1", start=start, end=end)
        await repository.save_ohlcv(bars)
        controller = ReplayController()
        replayer = MarketReplayer(repository, event_bus, signal_engine, risk_manager, order_manager, controller, run_id)
        received: list[BarCloseEvent] = []

        async def _on_bar(event: BaseEvent) -> None:
            if isinstance(event, BarCloseEvent):
                received.append(event)

        event_bus.subscribe(EventType.BAR_CLOSE, _on_bar)
        await replayer.start("EURUSD", "mock_dev", "H1", start, end, speed=float("inf"))
        assert len(received) == len(bars)
        assert all(
            first.timestamp_close <= second.timestamp_close
            for first, second in zip(received, received[1:], strict=False)
        )
    finally:
        await event_bus.stop()


@pytest.mark.asyncio
async def test_step_forward_and_pause_resume(tmp_path: Path) -> None:
    run_id = "test-replay-step"
    (
        event_bus,
        repository,
        _indicator_engine,
        _regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path)
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=8)
        bars = generate_synthetic_bars(symbol="EURUSD", broker="mock_dev", timeframe="H1", start=start, end=end)
        await repository.save_ohlcv(bars)
        controller = ReplayController()
        replayer = MarketReplayer(repository, event_bus, signal_engine, risk_manager, order_manager, controller, run_id)
        await replayer.start("EURUSD", "mock_dev", "H1", start, end, speed=float("inf"))
        await replayer.jump_to(start + timedelta(hours=2))
        controller.pause()
        state_before = replayer.get_current_state()["index"]
        await replayer.step_forward(1)
        state_after = replayer.get_current_state()["index"]
        assert state_after == state_before + 1
        controller.resume()
    finally:
        await event_bus.stop()


@pytest.mark.asyncio
async def test_jump_to_positions_cursor(tmp_path: Path) -> None:
    run_id = "test-replay-jump"
    (
        event_bus,
        repository,
        _indicator_engine,
        _regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path)
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=10)
        bars = generate_synthetic_bars(symbol="EURUSD", broker="mock_dev", timeframe="H1", start=start, end=end)
        await repository.save_ohlcv(bars)
        controller = ReplayController()
        replayer = MarketReplayer(repository, event_bus, signal_engine, risk_manager, order_manager, controller, run_id)
        await replayer.start("EURUSD", "mock_dev", "H1", start, end, speed=float("inf"))
        await replayer.jump_to(start + timedelta(hours=5))
        state = replayer.get_current_state()
        assert state["index"] >= 0
    finally:
        await event_bus.stop()
