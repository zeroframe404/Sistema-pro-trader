from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.config_models import AntiOvertradingConfig, FiltersConfig, SignalsConfig
from core.event_types import EventType
from core.events import BarCloseEvent, BaseEvent
from execution.fill_simulator import FillSimulator
from replay.market_replayer import MarketReplayer
from replay.replay_controller import ReplayController
from replay.shadow_mode import ShadowMode
from risk.slippage_model import SlippageModel


@pytest.mark.asyncio
async def test_replay_pipeline_event_count_pause_and_step(tmp_path: Path) -> None:
    run_id = "it-replay-pipeline"
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
        end = start + timedelta(hours=100)
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

        await replayer.jump_to(start + timedelta(hours=10))
        controller.pause()
        paused_index = replayer.get_current_state()["index"]
        await asyncio.sleep(0.02)
        assert replayer.get_current_state()["index"] == paused_index
        await replayer.step_forward(5)
        assert replayer.get_current_state()["index"] == paused_index + 5
    finally:
        await event_bus.stop()


@pytest.mark.asyncio
async def test_shadow_mode_with_replay_generates_signals(tmp_path: Path) -> None:
    run_id = "it-replay-shadow"
    signals_cfg = SignalsConfig(
        filters=FiltersConfig(
            regime_filter=False,
            news_filter=False,
            session_filter=False,
            spread_filter=False,
            correlation_filter=False,
        ),
        anti_overtrading=AntiOvertradingConfig(enabled=False),
    )
    (
        event_bus,
        repository,
        _indicator_engine,
        _regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path, signals_config=signals_cfg)
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=100)
        bars = generate_synthetic_bars(symbol="EURUSD", broker="mock_dev", timeframe="H1", start=start, end=end)
        await repository.save_ohlcv(bars)
        shadow = ShadowMode(
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            fill_simulator=FillSimulator(slippage_model=SlippageModel()),
            event_bus=event_bus,
            logger=__import__("core.logger", fromlist=["get_logger"]).get_logger("tests.it.shadow"),
            run_id=run_id,
        )
        await shadow.start()
        controller = ReplayController()
        replayer = MarketReplayer(repository, event_bus, signal_engine, risk_manager, order_manager, controller, run_id)
        await replayer.start("EURUSD", "mock_dev", "H1", start, end, speed=float("inf"))
        await shadow.stop()
        assert len(shadow.get_shadow_trades()) >= 1
    finally:
        await event_bus.stop()
