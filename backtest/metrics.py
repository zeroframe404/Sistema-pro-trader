"""Performance metrics calculator for backtests."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import cast

import numpy as np
from numpy.typing import NDArray

from backtest.backtest_models import BacktestMetrics, BacktestTrade


class MetricsCalculator:
    """Compute full performance metrics from trade/equity inputs."""

    def calculate(
        self,
        trades: list[BacktestTrade],
        equity_curve: list[tuple[datetime, float]],
        initial_capital: float,
        risk_free_rate: float = 0.02,
    ) -> BacktestMetrics:
        """Compute all metrics in one pass with safe defaults for edge cases."""

        if initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")

        total_trades = len(trades)
        winners = [trade for trade in trades if trade.pnl_net > 0]
        losers = [trade for trade in trades if trade.pnl_net < 0]
        breakeven = total_trades - len(winners) - len(losers)
        win_rate = (len(winners) / total_trades) if total_trades else 0.0

        total_pnl = float(sum(trade.pnl for trade in trades))
        total_pnl_net = float(sum(trade.pnl_net for trade in trades))
        total_commission = float(sum(trade.commission for trade in trades))
        total_slippage = float(sum(trade.slippage for trade in trades))

        avg_pnl_per_trade = total_pnl_net / total_trades if total_trades else 0.0
        avg_pnl_winners = float(np.mean([trade.pnl_net for trade in winners])) if winners else 0.0
        avg_pnl_losers = float(np.mean([trade.pnl_net for trade in losers])) if losers else 0.0

        profit_factor = self.profit_factor(trades)
        expectancy = self.expectancy(trades)
        payoff_ratio = abs(avg_pnl_winners / avg_pnl_losers) if avg_pnl_losers < 0 else 0.0
        avg_r_multiple = (
            float(np.mean([trade.r_multiple for trade in trades if trade.r_multiple is not None]))
            if trades
            else 0.0
        )

        max_dd, dd_duration, _, _ = self.max_drawdown(equity_curve)
        drawdowns = self._drawdown_series(equity_curve)
        avg_drawdown = float(np.mean(drawdowns)) if drawdowns.size > 0 else 0.0
        ulcer = self.ulcer_index(equity_curve)

        returns = self._returns_from_equity(equity_curve)
        sharpe = self.sharpe_ratio(returns, risk_free_rate=risk_free_rate, periods_per_year=252)
        sortino = self.sortino_ratio(returns, risk_free_rate=risk_free_rate, periods_per_year=252)
        calmar = self.calmar_ratio(equity_curve, periods_per_year=252)
        omega = self.omega_ratio(returns, threshold=0.0)

        longest_winning_streak, longest_losing_streak = self._streaks(trades)
        monthly_returns = self.monthly_returns_dict(equity_curve)
        yearly_returns = self._yearly_returns_dict(equity_curve)
        stability = self.stability_score(monthly_returns)
        avg_bars_in_trade = float(np.mean([trade.bars_held for trade in trades])) if trades else 0.0
        avg_bars_between = self._avg_bars_between_trades(trades)
        trades_per_month = self._trades_per_month(trades)

        return BacktestMetrics(
            total_trades=total_trades,
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=win_rate,
            breakeven_trades=breakeven,
            total_pnl=total_pnl,
            total_pnl_net=total_pnl_net,
            total_commission=total_commission,
            total_slippage=total_slippage,
            avg_pnl_per_trade=avg_pnl_per_trade,
            avg_pnl_winners=avg_pnl_winners,
            avg_pnl_losers=avg_pnl_losers,
            profit_factor=profit_factor,
            expectancy=expectancy,
            payoff_ratio=payoff_ratio,
            avg_r_multiple=avg_r_multiple,
            max_drawdown_pct=max_dd,
            max_drawdown_duration_bars=dd_duration,
            avg_drawdown_pct=avg_drawdown,
            ulcer_index=ulcer,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            omega_ratio=omega,
            longest_winning_streak=longest_winning_streak,
            longest_losing_streak=longest_losing_streak,
            monthly_returns=monthly_returns,
            yearly_returns=yearly_returns,
            stability_score=stability,
            avg_bars_in_trade=avg_bars_in_trade,
            avg_bars_between_trades=avg_bars_between,
            trades_per_month=trades_per_month,
        )

    def sharpe_ratio(
        self,
        returns: np.ndarray,
        risk_free_rate: float = 0.02,
        periods_per_year: int = 252,
    ) -> float:
        """Annualized Sharpe ratio with division-by-zero guard."""

        if returns.size == 0:
            return 0.0
        rf_per_period = risk_free_rate / max(periods_per_year, 1)
        excess = returns - rf_per_period
        std = float(np.std(excess))
        if std <= 1e-12:
            return 0.0
        return float((np.mean(excess) / std) * math.sqrt(periods_per_year))

    def sortino_ratio(
        self,
        returns: np.ndarray,
        risk_free_rate: float = 0.02,
        periods_per_year: int = 252,
    ) -> float:
        """Annualized Sortino ratio using downside deviation only."""

        if returns.size == 0:
            return 0.0
        rf_per_period = risk_free_rate / max(periods_per_year, 1)
        excess = returns - rf_per_period
        downside = np.minimum(excess, 0.0)
        downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
        mean_excess = float(np.mean(excess))
        if downside_deviation <= 1e-12:
            return float("inf") if mean_excess > 0 else 0.0
        return float((mean_excess / downside_deviation) * math.sqrt(periods_per_year))

    def max_drawdown(self, equity_curve: list[tuple[datetime, float]]) -> tuple[float, int, datetime, datetime]:
        """Return max drawdown pct, duration bars, and timestamps for peak/trough."""

        if not equity_curve:
            now = datetime.now()
            return 0.0, 0, now, now

        peak_value = equity_curve[0][1]
        peak_dt = equity_curve[0][0]
        trough_dt = peak_dt
        max_dd = 0.0
        max_duration = 0
        duration = 0

        for ts, value in equity_curve:
            if value >= peak_value:
                peak_value = value
                peak_dt = ts
                duration = 0
            else:
                duration += 1
                dd = ((peak_value - value) / peak_value) * 100.0 if peak_value > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
                    trough_dt = ts
                    max_duration = duration

        return float(max_dd), max_duration, peak_dt, trough_dt

    def ulcer_index(self, equity_curve: list[tuple[datetime, float]]) -> float:
        """Ulcer index over drawdown percentage series."""

        drawdowns = self._drawdown_series(equity_curve)
        if drawdowns.size == 0:
            return 0.0
        return float(math.sqrt(float(np.mean(np.square(drawdowns)))))

    def profit_factor(self, trades: list[BacktestTrade]) -> float:
        """Gross profit divided by absolute gross loss."""

        gross_profit = sum(trade.pnl_net for trade in trades if trade.pnl_net > 0)
        gross_loss = abs(sum(trade.pnl_net for trade in trades if trade.pnl_net < 0))
        if gross_loss <= 1e-12:
            return float("inf") if gross_profit > 0 else 0.0
        return float(gross_profit / gross_loss)

    def expectancy(self, trades: list[BacktestTrade]) -> float:
        """Monetary expectancy per trade."""

        if not trades:
            return 0.0
        winners = [trade.pnl_net for trade in trades if trade.pnl_net > 0]
        losers = [abs(trade.pnl_net) for trade in trades if trade.pnl_net < 0]
        win_rate = len(winners) / len(trades)
        loss_rate = len(losers) / len(trades)
        avg_win = float(np.mean(winners)) if winners else 0.0
        avg_loss = float(np.mean(losers)) if losers else 0.0
        return float((win_rate * avg_win) - (loss_rate * avg_loss))

    def calmar_ratio(self, equity_curve: list[tuple[datetime, float]], periods_per_year: int = 252) -> float:
        """CAGR divided by max drawdown."""

        if len(equity_curve) < 2:
            return 0.0
        start_value = equity_curve[0][1]
        end_value = equity_curve[-1][1]
        if start_value <= 0:
            return 0.0
        n_periods = len(equity_curve) - 1
        years = n_periods / max(periods_per_year, 1)
        if years <= 0:
            return 0.0
        cagr = (end_value / start_value) ** (1 / years) - 1
        max_dd_pct, _, _, _ = self.max_drawdown(equity_curve)
        max_dd = max_dd_pct / 100.0
        if max_dd <= 1e-12:
            return 0.0
        return float(cagr / max_dd)

    def omega_ratio(self, returns: np.ndarray, threshold: float = 0.0) -> float:
        """Omega ratio for returns above/below threshold."""

        if returns.size == 0:
            return 0.0
        gains = np.maximum(returns - threshold, 0.0)
        losses = np.maximum(threshold - returns, 0.0)
        loss_sum = float(np.sum(losses))
        if loss_sum <= 1e-12:
            return float("inf")
        return float(np.sum(gains) / loss_sum)

    def stability_score(self, monthly_returns: dict[str, float]) -> float:
        """Return consistency score in [0, 1]."""

        if not monthly_returns:
            return 0.0
        values = np.array(list(monthly_returns.values()), dtype=float)
        mean_abs = float(np.mean(np.abs(values)))
        if mean_abs <= 1e-12:
            return 0.0
        raw = 1.0 - (float(np.std(values)) / mean_abs)
        return float(min(1.0, max(0.0, raw)))

    def monthly_returns_dict(self, equity_curve: list[tuple[datetime, float]]) -> dict[str, float]:
        """Return month key to pct return map."""

        if len(equity_curve) < 2:
            return {}
        month_points: dict[str, list[float]] = defaultdict(list)
        for ts, value in equity_curve:
            month_points[ts.strftime("%Y-%m")].append(value)
        monthly: dict[str, float] = {}
        for month, points in month_points.items():
            if len(points) < 2:
                monthly[month] = 0.0
                continue
            start = points[0]
            end = points[-1]
            monthly[month] = ((end - start) / start) * 100.0 if start > 0 else 0.0
        return dict(sorted(monthly.items()))

    def _yearly_returns_dict(self, equity_curve: list[tuple[datetime, float]]) -> dict[str, float]:
        year_points: dict[str, list[float]] = defaultdict(list)
        for ts, value in equity_curve:
            year_points[ts.strftime("%Y")].append(value)
        yearly: dict[str, float] = {}
        for year, points in year_points.items():
            if len(points) < 2:
                yearly[year] = 0.0
                continue
            start = points[0]
            end = points[-1]
            yearly[year] = ((end - start) / start) * 100.0 if start > 0 else 0.0
        return dict(sorted(yearly.items()))

    def _returns_from_equity(self, equity_curve: list[tuple[datetime, float]]) -> NDArray[np.float64]:
        if len(equity_curve) < 2:
            return np.array([], dtype=float)
        values = np.array([point[1] for point in equity_curve], dtype=float)
        prev = values[:-1]
        curr = values[1:]
        safe_prev = np.where(np.abs(prev) <= 1e-12, 1e-12, prev)
        return cast(NDArray[np.float64], np.asarray((curr - prev) / safe_prev, dtype=float))

    def _drawdown_series(self, equity_curve: list[tuple[datetime, float]]) -> NDArray[np.float64]:
        if not equity_curve:
            return np.array([], dtype=float)
        values = np.array([point[1] for point in equity_curve], dtype=float)
        peaks = np.maximum.accumulate(values)
        safe_peaks = np.where(np.abs(peaks) <= 1e-12, 1e-12, peaks)
        return cast(
            NDArray[np.float64],
            np.asarray(((safe_peaks - values) / safe_peaks) * 100.0, dtype=float),
        )

    def _streaks(self, trades: list[BacktestTrade]) -> tuple[int, int]:
        max_win = 0
        max_loss = 0
        current_win = 0
        current_loss = 0
        for trade in trades:
            if trade.pnl_net > 0:
                current_win += 1
                current_loss = 0
            elif trade.pnl_net < 0:
                current_loss += 1
                current_win = 0
            else:
                current_win = 0
                current_loss = 0
            max_win = max(max_win, current_win)
            max_loss = max(max_loss, current_loss)
        return max_win, max_loss

    def _avg_bars_between_trades(self, trades: list[BacktestTrade]) -> float:
        if len(trades) < 2:
            return 0.0
        ordered = sorted(trades, key=lambda item: item.entry_time)
        gaps = [(curr.entry_time - prev.exit_time).total_seconds() for prev, curr in zip(ordered, ordered[1:], strict=False)]
        if not gaps:
            return 0.0
        return float(np.mean(gaps))

    def _trades_per_month(self, trades: list[BacktestTrade]) -> float:
        if not trades:
            return 0.0
        months = {trade.entry_time.strftime("%Y-%m") for trade in trades}
        if not months:
            return 0.0
        return len(trades) / len(months)


__all__ = ["MetricsCalculator"]
