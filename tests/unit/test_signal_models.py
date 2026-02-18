from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from data.asset_types import AssetClass
from regime.regime_models import TrendRegime
from signals.signal_models import (
    DecisionResult,
    EnsembleResult,
    Signal,
    SignalDirection,
    SignalReason,
    SignalStrength,
)
from tests.unit._signal_fixtures import make_regime, make_signal


def test_signal_confidence_out_of_range_fails() -> None:
    with pytest.raises(ValidationError):
        make_signal(confidence=1.5)


def test_signal_invalid_direction_fails() -> None:
    with pytest.raises(ValidationError):
        Signal.model_validate(
            {
                "strategy_id": "x",
                "strategy_version": "1.0.0",
                "symbol": "EURUSD",
                "broker": "mock",
                "timeframe": "H1",
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": "run",
                "direction": "INVALID",
                "strength": "none",
                "raw_score": 0,
                "confidence": 0.5,
                "reasons": [],
                "regime": make_regime().model_dump(mode="json"),
                "horizon": "2h",
            }
        )


def test_decision_result_json_roundtrip() -> None:
    ensemble = EnsembleResult(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        timestamp=datetime.now(UTC),
        run_id="run",
        final_direction=SignalDirection.BUY,
        final_confidence=0.8,
        final_strength=SignalStrength.STRONG,
        agreement_score=1.0,
        contradiction_score=0.0,
        regime=make_regime(),
        horizon="2h",
    )
    decision = DecisionResult(
        ensemble=ensemble,
        display_decision="COMPRAR",
        display_color="green",
        display_emoji="🟢",
        confidence_percent=80,
        computed_at=datetime.now(UTC),
        valid_until=datetime.now(UTC) + timedelta(hours=2),
        asset_class=AssetClass.FOREX,
        horizon_human="2 horas",
    )

    parsed = DecisionResult.model_validate_json(decision.model_dump_json())
    assert parsed.display_decision == "COMPRAR"
    assert parsed.confidence_percent == 80


def test_signal_reason_contribution_out_of_range_fails() -> None:
    with pytest.raises(ValidationError):
        SignalReason(
            factor="rsi",
            value=70,
            contribution=1.4,
            weight=0.2,
            description="bad",
            direction="bullish",
            source="indicator",
        )


def test_ensemble_agreement_unanimous() -> None:
    signals = [make_signal(direction=SignalDirection.BUY, confidence=0.6) for _ in range(3)]
    agreement = 1.0 if all(item.direction == SignalDirection.BUY for item in signals) else 0.0
    ensemble = EnsembleResult(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        timestamp=datetime.now(UTC),
        run_id="run",
        final_direction=SignalDirection.BUY,
        final_confidence=0.7,
        final_strength=SignalStrength.MODERATE,
        contributing_signals=signals,
        agreement_score=agreement,
        contradiction_score=0.0,
        regime=make_regime(trend=TrendRegime.WEAK_UPTREND),
        horizon="2h",
    )
    assert ensemble.agreement_score == 1.0
