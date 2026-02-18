from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backtest.metrics import MetricsCalculator
from tests.unit._backtest_fixtures import make_equity_curve, make_trade


def test_sharpe_known_returns() -> None:
    calc = MetricsCalculator()
    returns = np.array([0.01, 0.0, 0.02, -0.01, 0.015], dtype=float)
    sharpe = calc.sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=1)
    manual = float(np.mean(returns) / np.std(returns))
    assert sharpe == pytest.approx(manual, rel=1e-3)


def test_sharpe_flat_series_is_zero() -> None:
    calc = MetricsCalculator()
    returns = np.array([0.0, 0.0, 0.0], dtype=float)
    assert calc.sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=1) == 0.0


def test_sortino_can_exceed_sharpe() -> None:
    calc = MetricsCalculator()
    returns = np.array([0.02, 0.02, 0.015, -0.001], dtype=float)
    sortino = calc.sortino_ratio(returns, risk_free_rate=0.0, periods_per_year=1)
    sharpe = calc.sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=1)
    assert sortino > sharpe


def test_max_drawdown_detects_worst_drop() -> None:
    calc = MetricsCalculator()
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    curve = [
        (ts, 100.0),
        (ts + timedelta(days=1), 110.0),
        (ts + timedelta(days=2), 90.0),
        (ts + timedelta(days=3), 95.0),
    ]
    max_dd, _, _, _ = calc.max_drawdown(curve)
    assert max_dd == pytest.approx((110.0 - 90.0) / 110.0 * 100.0)


def test_max_drawdown_monotonic_growth_is_zero() -> None:
    calc = MetricsCalculator()
    curve = make_equity_curve(100.0, [10.0, 5.0, 1.0])
    max_dd, _, _, _ = calc.max_drawdown(curve)
    assert max_dd == 0.0


def test_profit_factor_only_winners_is_inf() -> None:
    calc = MetricsCalculator()
    trades = [make_trade(idx=1, pnl_net=10.0), make_trade(idx=2, pnl_net=5.0)]
    assert calc.profit_factor(trades) == float("inf")


def test_profit_factor_only_losers_is_zero() -> None:
    calc = MetricsCalculator()
    trades = [make_trade(idx=1, pnl_net=-10.0), make_trade(idx=2, pnl_net=-5.0)]
    assert calc.profit_factor(trades) == 0.0


def test_expectancy_sign_cases() -> None:
    calc = MetricsCalculator()
    pos = [make_trade(idx=i, pnl_net=15.0) for i in range(6)] + [make_trade(idx=100 + i, pnl_net=-10.0) for i in range(4)]
    neg = [make_trade(idx=i, pnl_net=10.0) for i in range(4)] + [make_trade(idx=100 + i, pnl_net=-10.0) for i in range(6)]
    assert calc.expectancy(pos) > 0
    assert calc.expectancy(neg) < 0


def test_ulcer_index_flat_or_up_is_zero() -> None:
    calc = MetricsCalculator()
    curve = make_equity_curve(100.0, [0.0, 0.0, 0.0])
    assert calc.ulcer_index(curve) == 0.0


def test_monthly_returns_count_and_stability_bounds() -> None:
    calc = MetricsCalculator()
    curve = []
    value = 100.0
    for month in range(1, 5):
        curve.append((datetime(2024, month, 1, tzinfo=UTC), value))
        value += 5.0
        curve.append((datetime(2024, month, 28, tzinfo=UTC), value))
    monthly = calc.monthly_returns_dict(curve)
    assert len(monthly) == 4
    assert calc.stability_score(monthly) > 0.9


def test_stability_low_when_monthly_variance_high() -> None:
    calc = MetricsCalculator()
    monthly = {"2024-01": 10.0, "2024-02": -9.0, "2024-03": 12.0, "2024-04": -11.0}
    assert calc.stability_score(monthly) < 0.3
