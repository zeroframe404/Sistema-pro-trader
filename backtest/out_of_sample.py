"""Out-of-sample validation helpers for module 5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from backtest.backtest_models import BacktestConfig, BacktestMode, BacktestResult

if TYPE_CHECKING:
    from backtest.backtest_engine import BacktestEngine


class OutOfSampleValidator:
    """Split IS/OOS periods with purging and compare robustness."""

    def __init__(self, engine: BacktestEngine, config: BacktestConfig) -> None:
        self._engine = engine
        self._config = config

    async def run(self) -> tuple[BacktestResult, BacktestResult]:
        """Run in-sample then out-of-sample backtests and return both results."""

        is_start, is_end, oos_start, oos_end = self.split_period(
            start=self._config.start_date,
            end=self._config.end_date,
            oos_pct=self._config.oos_pct,
            purge_bars=self._config.purge_bars,
            timeframe=self._config.timeframes[0],
        )
        original = self._engine.config
        try:
            self._engine.config = original.model_copy(
                update={
                    "start_date": is_start,
                    "end_date": is_end,
                    "mode": BacktestMode.SIMPLE,
                },
                deep=True,
            )
            is_result = await self._engine._run_simple()  # noqa: SLF001

            self._engine.config = original.model_copy(
                update={
                    "start_date": oos_start,
                    "end_date": oos_end,
                    "mode": BacktestMode.SIMPLE,
                },
                deep=True,
            )
            oos_result = await self._engine._run_simple()  # noqa: SLF001
            return is_result, oos_result
        finally:
            self._engine.config = original

    def split_period(
        self,
        start: datetime,
        end: datetime,
        oos_pct: float,
        purge_bars: int,
        timeframe: str,
    ) -> tuple[datetime, datetime, datetime, datetime]:
        """Calculate IS and OOS windows with purging/embargo in bar units."""

        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        total_seconds = max((end_utc - start_utc).total_seconds(), 0.0)
        oos_seconds = total_seconds * oos_pct
        is_end_raw = end_utc - timedelta(seconds=oos_seconds)
        tf_seconds = self._timeframe_seconds(timeframe)
        purge_seconds = purge_bars * tf_seconds
        embargo_seconds = purge_seconds
        is_end_purged = is_end_raw - timedelta(seconds=purge_seconds)
        oos_start_embargoed = is_end_raw + timedelta(seconds=embargo_seconds)
        return start_utc, is_end_purged, oos_start_embargoed, end_utc

    def generate_oos_report(self, is_result: BacktestResult, oos_result: BacktestResult) -> dict[str, Any]:
        """Generate compact OOS validation report and recommendations."""

        is_sharpe = is_result.metrics.sharpe_ratio
        oos_sharpe = oos_result.metrics.sharpe_ratio
        is_pf = is_result.metrics.profit_factor
        oos_pf = oos_result.metrics.profit_factor
        win_rate_delta = abs(oos_result.metrics.win_rate - is_result.metrics.win_rate)
        sharpe_ratio = (oos_sharpe / is_sharpe) if abs(is_sharpe) > 1e-12 else 0.0
        if sharpe_ratio >= 0.8 and oos_pf >= 1.0 and win_rate_delta <= 0.15:
            verdict = "validated"
        elif sharpe_ratio >= 0.5 and oos_pf >= 0.9:
            verdict = "marginal"
        else:
            verdict = "overfit"
        recommendations: list[str] = []
        if verdict == "overfit":
            recommendations.append("reduce strategy parameter complexity")
            recommendations.append("expand training period and retest")
        if oos_pf < 1.0:
            recommendations.append("improve risk/reward profile before live usage")
        if win_rate_delta > 0.15:
            recommendations.append("investigate distribution drift between IS and OOS")
        return {
            "is_vs_oos_sharpe_ratio": sharpe_ratio,
            "is_vs_oos_profit_factor": (oos_pf / is_pf) if is_pf not in {0.0, float("inf")} else 0.0,
            "verdict": verdict,
            "recommendations": recommendations,
        }

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


__all__ = ["OutOfSampleValidator"]
