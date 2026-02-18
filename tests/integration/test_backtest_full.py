from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backtest.backtest_engine import BacktestEngine
from backtest.backtest_models import BacktestConfig, BacktestMode
from backtest.report_generator import ReportGenerator
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.logger import get_logger
from data.asset_types import AssetClass


@pytest.mark.asyncio
async def test_backtest_full_end_to_end(tmp_path: Path) -> None:
    run_id = "it-backtest-full"
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
        end = start + timedelta(days=14)
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
            strategy_ids=["trend_following"],
            symbols=["EURUSD"],
            brokers=["mock_dev"],
            timeframes=["H1"],
            asset_classes=[AssetClass.FOREX],
            start_date=start,
            end_date=end,
            mode=BacktestMode.SIMPLE,
            initial_capital=10000.0,
            warmup_bars=100,
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
            logger=get_logger("tests.it.backtest_engine"),
        )
        result = await engine.run()
        assert result.metrics.total_trades >= 1
        assert result.metrics.total_pnl_net != 0.0
        assert len(result.equity_curve) >= 1
        assert result.metrics.sharpe_ratio is not None
        report = ReportGenerator(template_dir=Path("backtest/templates"))
        started = time.perf_counter()
        html = report.generate_html(result, tmp_path / "report.html")
        elapsed = time.perf_counter() - started
        assert html.exists()
        assert elapsed < 10.0
    finally:
        await event_bus.stop()
