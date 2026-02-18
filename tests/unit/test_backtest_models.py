from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backtest.backtest_models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestMode,
    WalkForwardWindow,
)
from data.asset_types import AssetClass
from risk.risk_models import OrderSide
from tests.unit._backtest_fixtures import make_trade


def _dt(days: int) -> datetime:
    return datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=days)


def test_backtest_config_fails_when_end_not_after_start() -> None:
    with pytest.raises(ValidationError):
        BacktestConfig(
            strategy_ids=["trend_following"],
            symbols=["EURUSD"],
            brokers=["mock_dev"],
            timeframes=["H1"],
            asset_classes=[AssetClass.FOREX],
            start_date=_dt(1),
            end_date=_dt(1),
            mode=BacktestMode.SIMPLE,
        )


def test_backtest_config_fails_when_oos_pct_invalid() -> None:
    with pytest.raises(ValidationError):
        BacktestConfig(
            strategy_ids=["trend_following"],
            symbols=["EURUSD"],
            brokers=["mock_dev"],
            timeframes=["H1"],
            asset_classes=[AssetClass.FOREX],
            start_date=_dt(0),
            end_date=_dt(1),
            mode=BacktestMode.OUT_OF_SAMPLE,
            oos_pct=1.5,
        )


def test_backtest_trade_r_multiple_computed_from_stop_loss() -> None:
    trade = make_trade(idx=0, pnl_net=10.0)
    assert trade.side == OrderSide.BUY
    assert trade.r_multiple is not None
    assert trade.r_multiple > 0.0


def test_backtest_metrics_roundtrip_json() -> None:
    metrics = BacktestMetrics(total_trades=10, win_rate=0.6, sharpe_ratio=1.2)
    payload = metrics.model_dump_json()
    loaded = BacktestMetrics.model_validate_json(payload)
    assert loaded.total_trades == 10
    assert loaded.sharpe_ratio == pytest.approx(1.2)


def test_walk_forward_window_degradation_score() -> None:
    train = BacktestMetrics(sharpe_ratio=2.0)
    test = BacktestMetrics(sharpe_ratio=1.0)
    window = WalkForwardWindow(
        window_id=1,
        train_start=_dt(0),
        train_end=_dt(10),
        test_start=_dt(11),
        test_end=_dt(20),
        train_metrics=train,
        test_metrics=test,
        best_params={},
        is_metrics=train,
    )
    assert window.degradation_score == pytest.approx(0.5)
