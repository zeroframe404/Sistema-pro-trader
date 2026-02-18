from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backtest.backtest_models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestMode,
    WalkForwardWindow,
)
from backtest.walk_forward import WalkForwardAnalyzer
from data.asset_types import AssetClass


class _EngineStub:
    async def run_single_strategy(self, strategy_id, params, start, end):  # type: ignore[no-untyped-def]
        _ = (strategy_id, params, start, end)
        return BacktestMetrics(sharpe_ratio=1.0, total_trades=10, profit_factor=1.2)


def _cfg() -> BacktestConfig:
    return BacktestConfig(
        strategy_ids=["trend_following"],
        symbols=["EURUSD"],
        brokers=["mock_dev"],
        timeframes=["H1"],
        asset_classes=[AssetClass.FOREX],
        start_date=datetime(2024, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=200),
        mode=BacktestMode.WALK_FORWARD,
        wf_train_periods=40,
        wf_test_periods=20,
        wf_step_periods=20,
    )


def test_generate_windows_count_and_order() -> None:
    analyzer = WalkForwardAnalyzer(_EngineStub(), _cfg())
    windows = analyzer.generate_windows(
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=200),
        train_periods=40,
        test_periods=20,
        step_periods=20,
        timeframe="H1",
    )
    assert len(windows) >= 3
    for train_start, train_end, test_start, test_end in windows:
        assert train_end < test_end
        assert train_end <= test_start
        assert train_start < train_end


def test_generate_windows_too_short_raises() -> None:
    analyzer = WalkForwardAnalyzer(_EngineStub(), _cfg())
    with pytest.raises(ValueError):
        analyzer.generate_windows(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            train_periods=40,
            test_periods=20,
            step_periods=20,
            timeframe="H1",
        )


def test_calculate_summary_overfit_detection() -> None:
    analyzer = WalkForwardAnalyzer(_EngineStub(), _cfg())
    train = BacktestMetrics(sharpe_ratio=2.0, total_trades=10)
    test = BacktestMetrics(sharpe_ratio=0.6, total_trades=10)
    windows = [
        WalkForwardWindow(
            window_id=idx,
            train_start=datetime(2024, 1, 1, tzinfo=UTC),
            train_end=datetime(2024, 1, 2, tzinfo=UTC),
            test_start=datetime(2024, 1, 3, tzinfo=UTC),
            test_end=datetime(2024, 1, 4, tzinfo=UTC),
            train_metrics=train,
            test_metrics=test,
            best_params={},
            is_metrics=train,
        )
        for idx in range(3)
    ]
    summary = analyzer.calculate_summary(windows)
    assert summary["avg_degradation_score"] < 0.5
    assert summary["overall_verdict"] == "overfit"
