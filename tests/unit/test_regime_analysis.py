from __future__ import annotations

from backtest.metrics import MetricsCalculator
from backtest.regime_analysis import RegimeAnalyzer
from tests.unit._backtest_fixtures import make_trade


def test_analyze_returns_metrics_for_present_regimes() -> None:
    analyzer = RegimeAnalyzer()
    trades = [make_trade(idx=1, regime="ranging"), make_trade(idx=2, regime="strong_uptrend")]
    analysis = analyzer.analyze(trades, MetricsCalculator())
    trend_metrics = analysis["trend_regime"]
    assert "ranging" in trend_metrics
    assert "strong_uptrend" in trend_metrics


def test_find_best_conditions_returns_labels() -> None:
    analyzer = RegimeAnalyzer()
    trades = [make_trade(idx=i, pnl_net=10.0 + i, regime="ranging") for i in range(5)]
    analysis = analyzer.analyze(trades, MetricsCalculator())
    best = analyzer.find_best_conditions(analysis)
    assert best


def test_generate_heatmap_data_shape_24x7() -> None:
    analyzer = RegimeAnalyzer()
    trades = [make_trade(idx=i, pnl_net=(-1) ** i * 5.0) for i in range(20)]
    heatmap = analyzer.generate_heatmap_data(trades)
    assert len(heatmap) == 7
    assert all(len(day_row) == 24 for day_row in heatmap.values())
