"""Correlation-aware throttling for simultaneous signals."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from signals.filters.filter_result import FilterResult
from signals.signal_models import Signal


class CorrelationFilter:
    """Prevent too many simultaneous correlated exposures."""

    def __init__(self, *, window_minutes: int = 60, group_limit: int = 2) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._group_limit = group_limit
        self._history: dict[str, deque[datetime]] = defaultdict(deque)

    def apply(self, signal: Signal) -> FilterResult:
        now = signal.timestamp.astimezone(UTC)
        group = self._correlation_group(signal.symbol)
        bucket = self._history[group]
        boundary = now - self._window
        while bucket and bucket[0] < boundary:
            bucket.popleft()
        if len(bucket) >= self._group_limit:
            return FilterResult(passed=False, reason=f"correlation_limit_{group}")
        return FilterResult(passed=True)

    def register(self, signal: Signal) -> None:
        group = self._correlation_group(signal.symbol)
        self._history[group].append(signal.timestamp.astimezone(UTC))

    @staticmethod
    def _correlation_group(symbol: str) -> str:
        upper = symbol.upper()
        if "USD" in upper:
            return "usd"
        if len(upper) >= 6:
            return upper[:3]
        return upper
