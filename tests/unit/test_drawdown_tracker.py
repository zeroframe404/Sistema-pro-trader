from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from risk.drawdown_tracker import DrawdownTracker


def test_daily_drawdown_zero_without_losses() -> None:
    tracker = DrawdownTracker()
    now = datetime.now(UTC)
    tracker.update(10000.0, now)
    tracker.update(10100.0, now + timedelta(minutes=1))
    assert tracker.daily_drawdown_pct == 0.0


def test_daily_drawdown_three_percent_case() -> None:
    tracker = DrawdownTracker()
    now = datetime.now(UTC)
    tracker.update(10000.0, now)
    tracker.update(9700.0, now + timedelta(minutes=1))
    assert tracker.daily_drawdown_pct == pytest.approx(3.0, rel=1e-6)
    assert tracker.is_daily_limit_reached(3.0) is True


def test_reset_daily_resets_peak() -> None:
    tracker = DrawdownTracker()
    now = datetime.now(UTC)
    tracker.update(10000.0, now)
    tracker.update(9500.0, now + timedelta(minutes=1))
    assert tracker.daily_drawdown_pct > 0
    tracker.reset_daily()
    assert tracker.daily_drawdown_pct == 0.0


def test_drawdown_uses_peak_not_session_start() -> None:
    tracker = DrawdownTracker()
    now = datetime.now(UTC)
    tracker.update(10000.0, now)
    tracker.update(11000.0, now + timedelta(minutes=1))
    tracker.update(10500.0, now + timedelta(minutes=2))
    assert tracker.daily_drawdown_pct == pytest.approx((11000.0 - 10500.0) / 11000.0 * 100.0, rel=1e-6)
