"""Real-time drawdown tracking utilities."""

from __future__ import annotations

from datetime import UTC, datetime


class DrawdownTracker:
    """Track drawdown over daily, weekly, and session windows."""

    def __init__(self) -> None:
        self._equity_curve: list[tuple[datetime, float]] = []
        self._peak_session: float | None = None
        self._peak_daily: float | None = None
        self._peak_weekly: float | None = None
        self._max_drawdown_pct = 0.0
        self._last_timestamp: datetime | None = None
        self._realized_pnl_today = 0.0
        self._realized_pnl_week = 0.0

    def update(self, current_equity: float, timestamp: datetime) -> None:
        """Update tracker from latest equity snapshot."""

        ts = self._normalize_ts(timestamp)
        self._last_timestamp = ts
        self._equity_curve.append((ts, current_equity))

        self._roll_periods_if_needed(ts, current_equity)
        self._peak_session = max(self._peak_session or current_equity, current_equity)
        self._peak_daily = max(self._peak_daily or current_equity, current_equity)
        self._peak_weekly = max(self._peak_weekly or current_equity, current_equity)

        current_dd = self._pct_drop(self._peak_session, current_equity)
        self._max_drawdown_pct = max(self._max_drawdown_pct, current_dd)

    def register_trade_close(self, pnl: float, timestamp: datetime) -> None:
        """Register a closed-trade realized PnL."""

        ts = self._normalize_ts(timestamp)
        if self._last_timestamp is None:
            self._last_timestamp = ts
        if self._last_timestamp.date() != ts.date():
            self._realized_pnl_today = 0.0
        if self._last_timestamp.isocalendar()[:2] != ts.isocalendar()[:2]:
            self._realized_pnl_week = 0.0
        self._realized_pnl_today += pnl
        self._realized_pnl_week += pnl
        self._last_timestamp = ts

    @property
    def daily_drawdown_pct(self) -> float:
        """Percent drop from current daily peak."""

        return self._compute_window_dd(self._peak_daily)

    @property
    def weekly_drawdown_pct(self) -> float:
        """Percent drop from current weekly peak."""

        return self._compute_window_dd(self._peak_weekly)

    @property
    def session_drawdown_pct(self) -> float:
        """Percent drop from session peak."""

        return self._compute_window_dd(self._peak_session)

    @property
    def max_drawdown_pct(self) -> float:
        """Max historical drawdown from session start."""

        return self._max_drawdown_pct

    @property
    def realized_pnl_today(self) -> float:
        return self._realized_pnl_today

    @property
    def realized_pnl_week(self) -> float:
        return self._realized_pnl_week

    def is_daily_limit_reached(self, limit_pct: float) -> bool:
        """Return True when daily drawdown hits/exceeds limit."""

        return self.daily_drawdown_pct >= limit_pct

    def is_weekly_limit_reached(self, limit_pct: float) -> bool:
        """Return True when weekly drawdown hits/exceeds limit."""

        return self.weekly_drawdown_pct >= limit_pct

    def get_equity_curve(self) -> list[tuple[datetime, float]]:
        """Return full equity curve."""

        return list(self._equity_curve)

    def reset_daily(self) -> None:
        """Reset daily peak to latest equity."""

        latest = self._equity_curve[-1][1] if self._equity_curve else 0.0
        self._peak_daily = latest
        self._realized_pnl_today = 0.0

    def _compute_window_dd(self, peak: float | None) -> float:
        if peak is None or not self._equity_curve:
            return 0.0
        current = self._equity_curve[-1][1]
        return self._pct_drop(peak, current)

    def _roll_periods_if_needed(self, ts: datetime, current_equity: float) -> None:
        if self._last_timestamp is None:
            return
        if ts.date() != self._last_timestamp.date():
            self._peak_daily = current_equity
            self._realized_pnl_today = 0.0
        if ts.isocalendar()[:2] != self._last_timestamp.isocalendar()[:2]:
            self._peak_weekly = current_equity
            self._realized_pnl_week = 0.0

    @staticmethod
    def _pct_drop(peak: float | None, current: float) -> float:
        if peak is None or peak <= 0:
            return 0.0
        return max((peak - current) / peak * 100.0, 0.0)

    @staticmethod
    def _normalize_ts(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
