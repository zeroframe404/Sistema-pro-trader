"""Regime compatibility filter for signals."""

from __future__ import annotations

from regime.regime_models import TrendRegime, VolatilityRegime
from signals.filters.filter_result import FilterResult
from signals.signal_models import Signal, SignalDirection


class RegimeFilter:
    """Block or attenuate signals based on market regime."""

    def apply(self, signal: Signal) -> FilterResult:
        regime = signal.regime

        if regime.volatility == VolatilityRegime.EXTREME:
            return FilterResult(passed=False, reason="extreme_volatility")

        if signal.direction == SignalDirection.BUY and regime.trend == TrendRegime.STRONG_DOWNTREND:
            return FilterResult(passed=False, reason="buy_vs_strong_downtrend")

        if signal.direction == SignalDirection.SELL and regime.trend == TrendRegime.STRONG_UPTREND:
            return FilterResult(passed=False, reason="sell_vs_strong_uptrend")

        if signal.strategy_id == "trend_following" and regime.trend == TrendRegime.RANGING:
            return FilterResult(passed=True, reason="trend_following_in_range", confidence_multiplier=0.70)

        return FilterResult(passed=True)
