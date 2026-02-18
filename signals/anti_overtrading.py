"""Anti-overtrading guardrails."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.config_models import AntiOvertradingConfig
from signals.signal_models import Signal


@dataclass(slots=True)
class AntiOvertradingDecision:
    """Decision from anti-overtrading checks."""

    allowed: bool
    reason: str | None = None


class AntiOvertradingGuard:
    """Track per-symbol activity to block excessive signal churn."""

    def __init__(self, config: AntiOvertradingConfig | None = None) -> None:
        self._config = config or AntiOvertradingConfig()
        self._signal_times: dict[str, deque[datetime]] = defaultdict(deque)
        self._last_signal: dict[str, datetime] = {}
        self._paused_until: dict[str, datetime] = {}
        self._loss_streak: dict[str, int] = defaultdict(int)

    def evaluate(self, signal: Signal, timeframe_seconds: int) -> AntiOvertradingDecision:
        """Check if signal can be emitted."""

        if not self._config.enabled:
            return AntiOvertradingDecision(allowed=True)

        key = f"{signal.strategy_id}|{signal.symbol}"
        now = signal.timestamp.astimezone(UTC)

        paused_until = self._paused_until.get(key)
        if paused_until is not None and now < paused_until:
            return AntiOvertradingDecision(allowed=False, reason="strategy_pause_after_losses")

        last = self._last_signal.get(key)
        if last is not None:
            cooldown_seconds = timeframe_seconds * self._config.cooldown_bars
            if (now - last).total_seconds() < cooldown_seconds:
                return AntiOvertradingDecision(allowed=False, reason="cooldown_bars")

        one_hour_ago = now - timedelta(hours=1)
        window = self._signal_times[key]
        while window and window[0] < one_hour_ago:
            window.popleft()
        if len(window) >= self._config.max_signals_per_hour:
            return AntiOvertradingDecision(allowed=False, reason="max_signals_per_hour")

        return AntiOvertradingDecision(allowed=True)

    def register_signal(self, signal: Signal) -> None:
        """Persist accepted signal in internal counters."""

        key = f"{signal.strategy_id}|{signal.symbol}"
        ts = signal.timestamp.astimezone(UTC)
        self._last_signal[key] = ts
        self._signal_times[key].append(ts)

    def register_outcome(self, strategy_id: str, symbol: str, *, won: bool, timestamp: datetime | None = None) -> None:
        """Track outcomes to enforce pause after consecutive losses."""

        key = f"{strategy_id}|{symbol}"
        if won:
            self._loss_streak[key] = 0
            return

        self._loss_streak[key] += 1
        if self._loss_streak[key] < self._config.consecutive_loss_pause_count:
            return

        now = (timestamp or datetime.now(UTC)).astimezone(UTC)
        self._paused_until[key] = now + timedelta(hours=self._config.pause_hours)
        self._loss_streak[key] = 0
