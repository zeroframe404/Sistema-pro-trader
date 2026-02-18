from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backtest.backtest_engine import BacktestEngine
from backtest.backtest_models import BacktestConfig, BacktestMode
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.logger import get_logger
from data.asset_types import AssetClass


@pytest.mark.asyncio
async def test_walk_forward_full_pipeline(tmp_path: Path) -> None:
    run_id = "it-wf-full"
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path)
    try:
        start = datetime(2023, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=30)
        bars = generate_synthetic_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            asset_class=AssetClass.FOREX,
        )
        await repository.save_ohlcv(bars)
        config = BacktestConfig(
            run_id=run_id,
            strategy_ids=["mean_reversion"],
            symbols=["EURUSD"],
            brokers=["mock_dev"],
            timeframes=["H1"],
            asset_classes=[AssetClass.FOREX],
            start_date=start,
            end_date=end,
            mode=BacktestMode.WALK_FORWARD,
            initial_capital=10000.0,
            warmup_bars=30,
            wf_train_periods=240,
            wf_test_periods=120,
            wf_step_periods=120,
        )
        engine = BacktestEngine(
            config=config,
            data_repository=repository,
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            indicator_engine=indicator_engine,
            regime_detector=regime_detector,
            event_bus=event_bus,
            order_manager=order_manager,
            logger=get_logger("tests.it.wf_engine"),
        )
        result = await engine.run()
        assert result.wf_windows is not None
        assert len(result.wf_windows) >= 3
        for window in result.wf_windows:
            assert window.train_metrics is not None
            assert window.test_metrics is not None
            assert float(window.degradation_score or 0.0) <= 1.0 + 2.0
    finally:
        await event_bus.stop()
