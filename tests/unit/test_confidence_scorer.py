from __future__ import annotations

from datetime import UTC, datetime

from regime.regime_models import LiquidityRegime, TrendRegime, VolatilityRegime
from signals.confidence_scorer import ConfidenceScorer
from signals.signal_models import EnsembleResult, SignalDirection, SignalStrength
from tests.unit._signal_fixtures import make_regime


def _ensemble(direction: SignalDirection, confidence: float) -> EnsembleResult:
    return EnsembleResult(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        timestamp=datetime.now(UTC),
        run_id="run",
        final_direction=direction,
        final_confidence=confidence,
        final_strength=SignalStrength.MODERATE,
        agreement_score=0.9,
        contradiction_score=0.1,
        regime=make_regime(),
        horizon="2h",
    )


def test_strong_signal_high_confidence() -> None:
    scorer = ConfidenceScorer()
    ensemble = _ensemble(SignalDirection.BUY, 0.85)
    score = scorer.score(ensemble)
    assert score > 0.75


def test_buy_in_strong_downtrend_is_penalized() -> None:
    scorer = ConfidenceScorer()
    ensemble = _ensemble(SignalDirection.BUY, 0.55)
    ensemble.regime.trend = TrendRegime.STRONG_DOWNTREND
    score = scorer.score(ensemble)
    assert score < 0.3


def test_extreme_volatility_caps_confidence() -> None:
    scorer = ConfidenceScorer()
    ensemble = _ensemble(SignalDirection.BUY, 0.9)
    ensemble.regime.volatility = VolatilityRegime.EXTREME
    score = scorer.score(ensemble)
    assert score <= 0.3


def test_illiquid_caps_confidence() -> None:
    scorer = ConfidenceScorer()
    ensemble = _ensemble(SignalDirection.BUY, 0.9)
    ensemble.regime.liquidity = LiquidityRegime.ILLIQUID
    score = scorer.score(ensemble)
    assert score <= 0.2


def test_display_confidence_mapping() -> None:
    scorer = ConfidenceScorer()
    pct, strength = scorer.get_display_confidence(0.8)
    assert pct == 80
    assert strength == SignalStrength.STRONG

    pct_low, strength_low = scorer.get_display_confidence(0.3)
    assert pct_low == 30
    assert strength_low == SignalStrength.NONE
