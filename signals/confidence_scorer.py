"""Final confidence scoring for ensemble results."""

from __future__ import annotations

from core.config_models import ConfidenceConfig
from regime.regime_models import LiquidityRegime, TrendRegime, VolatilityRegime
from signals.signal_models import EnsembleResult, SignalDirection, SignalStrength


class ConfidenceScorer:
    """Apply regime-aware penalties and display mapping to confidence scores."""

    def __init__(self, config: ConfidenceConfig | None = None) -> None:
        self._config = config or ConfidenceConfig()

    def score(self, ensemble: EnsembleResult) -> float:
        """Return adjusted confidence in [0, 1]."""

        confidence = ensemble.final_confidence
        confidence -= ensemble.contradiction_score * self._config.contradiction_penalty

        if not ensemble.regime.is_tradeable:
            confidence -= self._config.non_trade_penalty

        if self._is_regime_mismatch(ensemble.final_direction, ensemble.regime.trend):
            confidence -= self._config.regime_mismatch_penalty

        confidence = max(0.0, min(confidence, 1.0))

        if ensemble.regime.volatility == VolatilityRegime.EXTREME:
            confidence = min(confidence, self._config.extreme_volatility_cap)
        if ensemble.regime.liquidity == LiquidityRegime.ILLIQUID:
            confidence = min(confidence, self._config.illiquid_cap)

        return confidence

    def get_display_confidence(self, confidence: float) -> tuple[int, SignalStrength]:
        """Convert internal confidence to UI-friendly values."""

        pct = int(round(max(0.0, min(confidence, 1.0)) * 100))
        return pct, self._strength_for(confidence)

    def strength_for(self, confidence: float) -> SignalStrength:
        """Public strength mapping helper."""

        return self._strength_for(confidence)

    def _strength_for(self, confidence: float) -> SignalStrength:
        if confidence >= self._config.strong_threshold:
            return SignalStrength.STRONG
        if confidence >= self._config.moderate_threshold:
            return SignalStrength.MODERATE
        if confidence >= self._config.weak_threshold:
            return SignalStrength.WEAK
        return SignalStrength.NONE

    @staticmethod
    def _is_regime_mismatch(direction: SignalDirection, trend: TrendRegime) -> bool:
        if direction == SignalDirection.BUY:
            return trend == TrendRegime.STRONG_DOWNTREND
        if direction == SignalDirection.SELL:
            return trend == TrendRegime.STRONG_UPTREND
        return False
