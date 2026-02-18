from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.config_models import AntiOvertradingConfig, FiltersConfig, SignalsConfig
from execution.fill_simulator import FillSimulator
from replay.market_replayer import MarketReplayer
from replay.replay_controller import ReplayController
from replay.shadow_mode import ShadowMode
from risk.slippage_model import SlippageModel


def _shadow_signals_config() -> SignalsConfig:
    return SignalsConfig(
        filters=FiltersConfig(
            regime_filter=False,
            news_filter=False,
            session_filter=False,
            spread_filter=False,
            correlation_filter=False,
        ),
        anti_overtrading=AntiOvertradingConfig(enabled=False),
    )


@pytest.mark.asyncio
async def test_shadow_mode_generates_without_live_orders(tmp_path: Path) -> None:
    run_id = "test-shadow-orders"
    (
        event_bus,
        repository,
        _indicator_engine,
        _regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(
        run_id=run_id,
        data_store_path=tmp_path,
        signals_config=_shadow_signals_config(),
    )
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=60)
        bars = generate_synthetic_bars(symbol="EURUSD", broker="mock_dev", timeframe="H1", start=start, end=end)
        await repository.save_ohlcv(bars)
        shadow = ShadowMode(
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            fill_simulator=FillSimulator(slippage_model=SlippageModel()),
            event_bus=event_bus,
            logger=__import__("core.logger", fromlist=["get_logger"]).get_logger("tests.shadow"),
            run_id=run_id,
        )
        await shadow.start()
        controller = ReplayController()
        replayer = MarketReplayer(repository, event_bus, signal_engine, risk_manager, order_manager, controller, run_id)
        await replayer.start("EURUSD", "mock_dev", "H1", start, end, speed=float("inf"))
        await shadow.stop()
        assert len(shadow.get_shadow_trades()) >= 1
        assert len(order_manager.get_orders()) == 0
    finally:
        await event_bus.stop()


@pytest.mark.asyncio
async def test_compare_with_live_detects_divergence(tmp_path: Path) -> None:
    run_id = "test-shadow-divergence"
    (
        event_bus,
        repository,
        _indicator_engine,
        _regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(
        run_id=run_id,
        data_store_path=tmp_path,
        signals_config=_shadow_signals_config(),
    )
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=40)
        bars = generate_synthetic_bars(symbol="EURUSD", broker="mock_dev", timeframe="H1", start=start, end=end)
        await repository.save_ohlcv(bars)
        shadow = ShadowMode(
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            fill_simulator=FillSimulator(slippage_model=SlippageModel()),
            event_bus=event_bus,
            logger=__import__("core.logger", fromlist=["get_logger"]).get_logger("tests.shadow"),
            run_id=run_id,
        )
        await shadow.start()
        controller = ReplayController()
        replayer = MarketReplayer(repository, event_bus, signal_engine, risk_manager, order_manager, controller, run_id)
        await replayer.start("EURUSD", "mock_dev", "H1", start, end, speed=float("inf"))
        await shadow.stop()
        comparison = shadow.compare_with_live(
            [{"symbol": "EURUSD", "entry_time": "1900-01-01T00:00:00+00:00", "side": "BUY"}]
        )
        assert comparison["divergences"]
        assert 0.0 <= comparison["agreement_rate"] <= 1.0
    finally:
        await event_bus.stop()


@pytest.mark.asyncio
async def test_shadow_metrics_returns_valid_model(tmp_path: Path) -> None:
    run_id = "test-shadow-metrics"
    (
        event_bus,
        repository,
        _indicator_engine,
        _regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(
        run_id=run_id,
        data_store_path=tmp_path,
        signals_config=_shadow_signals_config(),
    )
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=24)
        bars = generate_synthetic_bars(symbol="EURUSD", broker="mock_dev", timeframe="H1", start=start, end=end)
        await repository.save_ohlcv(bars)
        shadow = ShadowMode(
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            fill_simulator=FillSimulator(slippage_model=SlippageModel()),
            event_bus=event_bus,
            logger=__import__("core.logger", fromlist=["get_logger"]).get_logger("tests.shadow"),
            run_id=run_id,
        )
        await shadow.start()
        controller = ReplayController()
        replayer = MarketReplayer(repository, event_bus, signal_engine, risk_manager, order_manager, controller, run_id)
        await replayer.start("EURUSD", "mock_dev", "H1", start, end, speed=float("inf"))
        await shadow.stop()
        metrics = shadow.get_shadow_metrics()
        assert metrics.total_trades >= 0
    finally:
        await event_bus.stop()
