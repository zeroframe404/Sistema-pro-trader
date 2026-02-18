"""Regime-level performance decomposition for backtest results."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from backtest.backtest_models import BacktestMetrics, BacktestTrade
from backtest.metrics import MetricsCalculator


class RegimeAnalyzer:
    """Analyze where a strategy performs best or worst."""

    def analyze(self, trades: list[BacktestTrade], metrics_calculator: MetricsCalculator) -> dict[str, Any]:
        """Compute grouped metrics across market condition dimensions."""

        grouped: dict[str, dict[str, list[BacktestTrade]]] = {
            "trend_regime": defaultdict(list),
            "volatility_regime": defaultdict(list),
            "session": defaultdict(list),
            "weekday": defaultdict(list),
            "hour": defaultdict(list),
            "month": defaultdict(list),
            "confidence_bucket": defaultdict(list),
        }
        for trade in trades:
            grouped["trend_regime"][trade.regime_at_entry].append(trade)
            grouped["volatility_regime"][trade.volatility_at_entry].append(trade)
            grouped["session"][self._session_for_hour(trade.entry_time.hour)].append(trade)
            grouped["weekday"][str(trade.entry_time.weekday())].append(trade)
            grouped["hour"][str(trade.entry_time.hour)].append(trade)
            grouped["month"][trade.entry_time.strftime("%Y-%m")].append(trade)
            grouped["confidence_bucket"][self._confidence_bucket(trade.signal_confidence)].append(trade)

        metrics_by_group: dict[str, dict[str, BacktestMetrics]] = {}
        for group_name, bucket_map in grouped.items():
            metrics_by_group[group_name] = {}
            for key, grouped_trades in bucket_map.items():
                metrics_by_group[group_name][key] = self._metrics_for_group(grouped_trades, metrics_calculator)
        return metrics_by_group

    def find_best_conditions(self, analysis: dict[str, Any]) -> list[str]:
        """Return top condition labels by Sharpe ratio."""

        candidates: list[tuple[str, float]] = []
        for group_name, group_values in analysis.items():
            if not isinstance(group_values, dict):
                continue
            for key, metric in group_values.items():
                if isinstance(metric, BacktestMetrics):
                    candidates.append((f"{group_name}:{key}", metric.sharpe_ratio))
        candidates.sort(key=lambda item: item[1], reverse=True)
        return [label for label, _ in candidates[:3]]

    def find_worst_conditions(self, analysis: dict[str, Any]) -> list[str]:
        """Return worst condition labels by Sharpe ratio."""

        candidates: list[tuple[str, float]] = []
        for group_name, group_values in analysis.items():
            if not isinstance(group_values, dict):
                continue
            for key, metric in group_values.items():
                if isinstance(metric, BacktestMetrics):
                    candidates.append((f"{group_name}:{key}", metric.sharpe_ratio))
        candidates.sort(key=lambda item: item[1])
        return [label for label, _ in candidates[:3]]

    def generate_heatmap_data(self, trades: list[BacktestTrade]) -> dict[str, dict[str, float]]:
        """Return day-hour average pnl matrix compatible with 24x7 heatmaps."""

        pnl_map: dict[int, dict[int, list[float]]] = {day: {hour: [] for hour in range(24)} for day in range(7)}
        for trade in trades:
            day = trade.entry_time.weekday()
            hour = trade.entry_time.hour
            pnl_map[day][hour].append(trade.pnl_net)

        result: dict[str, dict[str, float]] = {}
        for day in range(7):
            row: dict[str, float] = {}
            for hour in range(24):
                values = pnl_map[day][hour]
                row[str(hour)] = (sum(values) / len(values)) if values else 0.0
            result[str(day)] = row
        return result

    def _metrics_for_group(self, trades: list[BacktestTrade], calculator: MetricsCalculator) -> BacktestMetrics:
        if not trades:
            return BacktestMetrics()
        ordered = sorted(trades, key=lambda item: item.exit_time)
        equity = 10000.0
        curve: list[tuple[datetime, float]] = []
        for trade in ordered:
            equity += trade.pnl_net
            curve.append((trade.exit_time.astimezone(UTC), equity))
        if not curve:
            curve = [(datetime.now(UTC), 10000.0)]
        return calculator.calculate(ordered, curve, initial_capital=10000.0)

    def _confidence_bucket(self, confidence: float) -> str:
        if confidence < 0.40:
            return "0-40%"
        if confidence < 0.60:
            return "40-60%"
        if confidence < 0.80:
            return "60-80%"
        return "80-100%"

    def _session_for_hour(self, hour: int) -> str:
        if 0 <= hour < 7:
            return "asia"
        if 7 <= hour < 12:
            return "london"
        if 12 <= hour < 16:
            return "overlap"
        if 16 <= hour < 21:
            return "newyork"
        return "byma"


__all__ = ["RegimeAnalyzer"]
