"""Signal ensemble combination strategies."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime

from regime.regime_models import MarketRegime
from signals.signal_models import EnsembleResult, Signal, SignalDirection, SignalStrength


class SignalEnsemble:
    """Combine strategy-level signals into one final direction/confidence."""

    def __init__(
        self,
        *,
        strategy_weights: dict[str, float] | None = None,
        wait_threshold: float = 0.10,
        contradiction_threshold: float = 0.50,
    ) -> None:
        self._strategy_weights = strategy_weights or {}
        self._wait_threshold = wait_threshold
        self._contradiction_threshold = contradiction_threshold

    def combine(
        self,
        signals: list[Signal],
        regime: MarketRegime,
        method: str = "weighted_vote",
    ) -> EnsembleResult:
        """Combine multiple signals into one ensemble decision."""

        if not signals:
            return self._empty_result(regime=regime, direction=SignalDirection.NO_TRADE, confidence=0.0)

        if all(signal.direction == SignalDirection.WAIT for signal in signals):
            return self._empty_result(
                regime=regime,
                direction=SignalDirection.WAIT,
                confidence=0.2,
                signals=signals,
            )

        selected_method = method.lower()
        if selected_method == "majority_vote":
            direction, confidence = self._majority_vote(signals)
        elif selected_method == "unanimous":
            direction, confidence = self._unanimous(signals)
        elif selected_method == "best_confidence":
            direction, confidence = self._best_confidence(signals)
        elif selected_method == "regime_weighted":
            direction, confidence = self._regime_weighted(signals, regime)
        else:
            direction, confidence = self._weighted_vote(signals)

        agreement = self._calculate_agreement_score(signals)
        contradiction = 1.0 - agreement
        if (
            selected_method in {"weighted_vote", "majority_vote", "unanimous"}
            and contradiction >= self._contradiction_threshold
            and direction in {SignalDirection.BUY, SignalDirection.SELL}
        ):
            direction = SignalDirection.WAIT
            confidence = min(confidence, 0.45)

        return EnsembleResult(
            symbol=signals[0].symbol,
            broker=signals[0].broker,
            timeframe=signals[0].timeframe,
            timestamp=max(signal.timestamp for signal in signals).astimezone(UTC),
            run_id=signals[0].run_id,
            final_direction=direction,
            final_confidence=max(0.0, min(confidence, 1.0)),
            final_strength=self._confidence_to_strength(confidence),
            contributing_signals=signals,
            all_reasons=self._collect_reasons(signals),
            agreement_score=agreement,
            contradiction_score=contradiction,
            regime=regime,
            horizon=signals[0].horizon,
        )

    def _weighted_vote(self, signals: list[Signal]) -> tuple[SignalDirection, float]:
        total_score = 0.0
        weight_sum = 0.0
        for signal in signals:
            weight = self._strategy_weights.get(signal.strategy_id, 1.0)
            if signal.direction == SignalDirection.BUY:
                total_score += signal.confidence * weight
            elif signal.direction == SignalDirection.SELL:
                total_score -= signal.confidence * weight
            elif signal.direction == SignalDirection.NO_TRADE:
                total_score -= 0.15 * weight
            weight_sum += weight

        normalized = total_score / max(weight_sum, 1e-9)
        if abs(normalized) <= self._wait_threshold:
            return SignalDirection.WAIT, max(0.2, 0.5 - abs(normalized))
        if normalized > 0:
            return SignalDirection.BUY, min(1.0, abs(normalized))
        return SignalDirection.SELL, min(1.0, abs(normalized))

    @staticmethod
    def _majority_vote(signals: list[Signal]) -> tuple[SignalDirection, float]:
        directions = [signal.direction for signal in signals if signal.direction in {SignalDirection.BUY, SignalDirection.SELL}]
        if not directions:
            return SignalDirection.WAIT, 0.2
        count = Counter(directions)
        if count[SignalDirection.BUY] == count[SignalDirection.SELL]:
            return SignalDirection.WAIT, 0.3
        winner = SignalDirection.BUY if count[SignalDirection.BUY] > count[SignalDirection.SELL] else SignalDirection.SELL
        confidence = max(count.values()) / len(directions)
        return winner, confidence

    @staticmethod
    def _unanimous(signals: list[Signal]) -> tuple[SignalDirection, float]:
        actionable = [signal for signal in signals if signal.direction in {SignalDirection.BUY, SignalDirection.SELL}]
        if not actionable:
            return SignalDirection.WAIT, 0.2
        first = actionable[0].direction
        if any(signal.direction != first for signal in actionable):
            return SignalDirection.WAIT, 0.25
        confidence = sum(signal.confidence for signal in actionable) / len(actionable)
        return first, confidence

    @staticmethod
    def _best_confidence(signals: list[Signal]) -> tuple[SignalDirection, float]:
        actionable = [signal for signal in signals if signal.direction in {SignalDirection.BUY, SignalDirection.SELL}]
        if not actionable:
            return SignalDirection.WAIT, 0.2
        best = max(actionable, key=lambda item: item.confidence)
        return best.direction, best.confidence

    def _regime_weighted(
        self,
        signals: list[Signal],
        regime: MarketRegime,
    ) -> tuple[SignalDirection, float]:
        boosts = set(regime.recommended_strategies)
        total_score = 0.0
        total_weight = 0.0
        for signal in signals:
            base = self._strategy_weights.get(signal.strategy_id, 1.0)
            boost = 1.25 if signal.strategy_id in boosts else 1.0
            eff_weight = base * boost
            direction = 0.0
            if signal.direction == SignalDirection.BUY:
                direction = 1.0
            elif signal.direction == SignalDirection.SELL:
                direction = -1.0
            total_score += direction * signal.confidence * eff_weight
            total_weight += eff_weight

        normalized = total_score / max(total_weight, 1e-9)
        if abs(normalized) <= self._wait_threshold:
            return SignalDirection.WAIT, 0.35
        if normalized > 0:
            return SignalDirection.BUY, min(1.0, abs(normalized))
        return SignalDirection.SELL, min(1.0, abs(normalized))

    @staticmethod
    def _calculate_agreement_score(signals: list[Signal]) -> float:
        actionable = [signal.direction for signal in signals if signal.direction in {SignalDirection.BUY, SignalDirection.SELL}]
        if not actionable:
            return 0.0
        count = Counter(actionable)
        return max(count.values()) / len(actionable)

    @staticmethod
    def _confidence_to_strength(confidence: float) -> SignalStrength:
        if confidence >= 0.75:
            return SignalStrength.STRONG
        if confidence >= 0.55:
            return SignalStrength.MODERATE
        if confidence >= 0.40:
            return SignalStrength.WEAK
        return SignalStrength.NONE

    @staticmethod
    def _collect_reasons(signals: Iterable[Signal]) -> list:
        reasons = []
        for signal in signals:
            reasons.extend(signal.reasons)
        if not reasons:
            return []
        total = sum(item.weight for item in reasons)
        if total <= 0:
            return sorted(reasons, key=lambda item: item.weight, reverse=True)
        normalized = [
            item.model_copy(update={"weight": item.weight / total})
            for item in reasons
        ]
        return sorted(normalized, key=lambda item: item.weight, reverse=True)

    def _empty_result(
        self,
        *,
        regime: MarketRegime,
        direction: SignalDirection,
        confidence: float,
        signals: list[Signal] | None = None,
    ) -> EnsembleResult:
        now = datetime.now(UTC)
        source = signals[0] if signals else None
        return EnsembleResult(
            symbol=source.symbol if source else regime.symbol,
            broker=source.broker if source else "unknown",
            timeframe=source.timeframe if source else regime.timeframe,
            timestamp=now,
            run_id=source.run_id if source else "unknown",
            final_direction=direction,
            final_confidence=confidence,
            final_strength=self._confidence_to_strength(confidence),
            contributing_signals=signals or [],
            all_reasons=[],
            agreement_score=0.0,
            contradiction_score=1.0 if direction == SignalDirection.WAIT else 0.0,
            regime=regime,
            horizon=source.horizon if source else "unknown",
        )
