from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.config_models import AntiOvertradingConfig
from signals.anti_overtrading import AntiOvertradingGuard
from tests.unit._signal_fixtures import make_signal


def test_second_signal_within_cooldown_is_blocked() -> None:
    guard = AntiOvertradingGuard(AntiOvertradingConfig(cooldown_bars=3))
    first = make_signal()
    second = first.model_copy(update={"timestamp": first.timestamp + timedelta(minutes=30)})

    assert guard.evaluate(first, timeframe_seconds=900).allowed
    guard.register_signal(first)
    result = guard.evaluate(second, timeframe_seconds=900)
    assert not result.allowed
    assert result.reason == "cooldown_bars"


def test_signal_after_cooldown_is_allowed() -> None:
    guard = AntiOvertradingGuard(AntiOvertradingConfig(cooldown_bars=1))
    first = make_signal()
    second = first.model_copy(update={"timestamp": first.timestamp + timedelta(hours=2)})
    guard.register_signal(first)
    assert guard.evaluate(second, timeframe_seconds=3600).allowed


def test_fifth_signal_in_hour_is_blocked() -> None:
    guard = AntiOvertradingGuard(AntiOvertradingConfig(max_signals_per_hour=4, cooldown_bars=0))
    start = datetime.now(UTC)
    for idx in range(4):
        signal = make_signal().model_copy(update={"timestamp": start + timedelta(minutes=idx * 10)})
        assert guard.evaluate(signal, timeframe_seconds=60).allowed
        guard.register_signal(signal)

    blocked = make_signal().model_copy(update={"timestamp": start + timedelta(minutes=50)})
    result = guard.evaluate(blocked, timeframe_seconds=60)
    assert not result.allowed
    assert result.reason == "max_signals_per_hour"


def test_consecutive_losses_pause_strategy() -> None:
    guard = AntiOvertradingGuard(
        AntiOvertradingConfig(
            consecutive_loss_pause_count=3,
            pause_hours=2,
            cooldown_bars=0,
        )
    )
    key_time = datetime.now(UTC)
    for _ in range(3):
        guard.register_outcome("trend_following", "EURUSD", won=False, timestamp=key_time)

    signal = make_signal().model_copy(update={"timestamp": key_time + timedelta(minutes=5)})
    result = guard.evaluate(signal, timeframe_seconds=60)
    assert not result.allowed
    assert result.reason == "strategy_pause_after_losses"


def test_pause_resets_after_period() -> None:
    guard = AntiOvertradingGuard(
        AntiOvertradingConfig(
            consecutive_loss_pause_count=3,
            pause_hours=1,
            cooldown_bars=0,
        )
    )
    now = datetime.now(UTC)
    for _ in range(3):
        guard.register_outcome("trend_following", "EURUSD", won=False, timestamp=now)

    later = make_signal().model_copy(update={"timestamp": now + timedelta(hours=2)})
    result = guard.evaluate(later, timeframe_seconds=60)
    assert result.allowed


def test_register_signal_then_immediate_blocked() -> None:
    guard = AntiOvertradingGuard(AntiOvertradingConfig(cooldown_bars=2))
    signal = make_signal()
    guard.register_signal(signal)
    immediate = signal.model_copy(update={"timestamp": signal.timestamp + timedelta(minutes=1)})
    assert not guard.evaluate(immediate, timeframe_seconds=300).allowed
