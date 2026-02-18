"""Walk-forward analysis helpers for module 5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from backtest.backtest_models import BacktestConfig, WalkForwardWindow

if TYPE_CHECKING:
    from backtest.backtest_engine import BacktestEngine


class WalkForwardAnalyzer:
    """Generate and evaluate walk-forward train/test windows."""

    def __init__(self, engine: BacktestEngine, config: BacktestConfig) -> None:
        self._engine = engine
        self._config = config

    async def run(self) -> list[WalkForwardWindow]:
        """Run walk-forward analysis for the first strategy in config."""

        strategy_id = self._config.strategy_ids[0]
        windows = self.generate_windows(
            start=self._config.start_date,
            end=self._config.end_date,
            train_periods=self._config.wf_train_periods,
            test_periods=self._config.wf_test_periods,
            step_periods=self._config.wf_step_periods,
            timeframe=self._config.timeframes[0],
        )
        result: list[WalkForwardWindow] = []
        for idx, (train_start, train_end, test_start, test_end) in enumerate(windows):
            train_metrics = await self._engine.run_single_strategy(strategy_id, {}, train_start, train_end)
            test_metrics = await self._engine.run_single_strategy(strategy_id, {}, test_start, test_end)
            result.append(
                WalkForwardWindow(
                    window_id=idx,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_metrics=train_metrics,
                    test_metrics=test_metrics,
                    best_params={},
                    is_metrics=train_metrics,
                )
            )
        return result

    def generate_windows(
        self,
        start: datetime,
        end: datetime,
        train_periods: int,
        test_periods: int,
        step_periods: int,
        timeframe: str,
    ) -> list[tuple[datetime, datetime, datetime, datetime]]:
        """Generate rolling train/test windows."""

        tf_seconds = self._timeframe_seconds(timeframe)
        train_delta = timedelta(seconds=train_periods * tf_seconds)
        test_delta = timedelta(seconds=test_periods * tf_seconds)
        step_delta = timedelta(seconds=step_periods * tf_seconds)

        windows: list[tuple[datetime, datetime, datetime, datetime]] = []
        cursor = start.astimezone(UTC)
        hard_end = end.astimezone(UTC)
        while True:
            train_start = cursor
            train_end = train_start + train_delta
            test_start = train_end
            test_end = test_start + test_delta
            if test_end > hard_end:
                break
            windows.append((train_start, train_end, test_start, test_end))
            cursor = cursor + step_delta

        if len(windows) < 3:
            raise ValueError("period is too short to generate at least 3 walk-forward windows")
        return windows

    def calculate_summary(self, windows: list[WalkForwardWindow]) -> dict[str, Any]:
        """Return statistical summary for walk-forward results."""

        if not windows:
            return {
                "avg_degradation_score": 0.0,
                "pct_windows_profitable": 0.0,
                "sharpe_stability": 0.0,
                "overall_verdict": "overfit",
            }
        degradations = [float(window.degradation_score or 0.0) for window in windows]
        positive = [window for window in windows if window.test_metrics.sharpe_ratio > 0]
        test_sharpes = [window.test_metrics.sharpe_ratio for window in windows]
        avg_degradation = sum(degradations) / len(degradations)
        stability = float(self._std(test_sharpes))
        pct_profitable = len(positive) / len(windows)
        if avg_degradation >= 0.8 and pct_profitable >= 0.7:
            verdict = "robust"
        elif avg_degradation >= 0.5 and pct_profitable >= 0.5:
            verdict = "marginal"
        else:
            verdict = "overfit"
        return {
            "avg_degradation_score": avg_degradation,
            "pct_windows_profitable": pct_profitable,
            "sharpe_stability": stability,
            "overall_verdict": verdict,
        }

    def plot_windows(self, windows: list[WalkForwardWindow]) -> Any:
        """Build simple matplotlib chart for train/test windows."""

        try:
            import matplotlib.pyplot as plt
        except Exception:  # noqa: BLE001
            return None
        fig, axis = plt.subplots(figsize=(10, 3))
        for window in windows:
            axis.plot(
                [window.train_start.isoformat(), window.train_end.isoformat()],
                [window.window_id, window.window_id],
                color="steelblue",
                linewidth=4,
            )
            axis.plot(
                [window.test_start.isoformat(), window.test_end.isoformat()],
                [window.window_id, window.window_id],
                color="orange",
                linewidth=4,
            )
        axis.set_title("Walk-forward windows")
        axis.set_xlabel("Date")
        axis.set_ylabel("Window")
        return fig

    def _timeframe_seconds(self, timeframe: str) -> int:
        mapping = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "M30": 1800,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
            "W1": 604800,
            "MN1": 2592000,
        }
        return mapping.get(timeframe.upper(), 3600)

    def _std(self, values: list[float]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return float(variance ** 0.5)


__all__ = ["WalkForwardAnalyzer"]
