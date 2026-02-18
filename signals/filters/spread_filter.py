"""Spread spike filter."""

from __future__ import annotations

from signals.filters.filter_result import FilterResult
from signals.signal_models import Signal


class SpreadFilter:
    """Reject signals when spread multiplier is excessive."""

    def __init__(self, max_multiplier: float = 3.0) -> None:
        self._max_multiplier = max_multiplier

    def apply(
        self,
        signal: Signal,
        *,
        current_spread: float | None,
        average_spread: float | None,
    ) -> FilterResult:
        if current_spread is None or average_spread is None or average_spread <= 0:
            return FilterResult(passed=True)

        ratio = current_spread / average_spread
        if ratio > self._max_multiplier:
            return FilterResult(passed=False, reason="spread_spike")
        return FilterResult(passed=True)
