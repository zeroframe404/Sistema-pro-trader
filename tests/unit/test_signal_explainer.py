from __future__ import annotations

from datetime import UTC, datetime

from signals.signal_explainer import SignalExplainer, _horizon_to_human
from signals.signal_models import EnsembleResult, SignalDirection, SignalReason, SignalStrength
from tests.unit._signal_fixtures import make_regime


def _ensemble(direction: SignalDirection) -> EnsembleResult:
    return EnsembleResult(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        timestamp=datetime.now(UTC),
        run_id="run",
        final_direction=direction,
        final_confidence=0.78,
        final_strength=SignalStrength.STRONG,
        agreement_score=0.9,
        contradiction_score=0.1,
        regime=make_regime(),
        horizon="2h",
        all_reasons=[
            SignalReason(
                factor="RSI",
                value=28.5,
                contribution=0.3,
                weight=0.25,
                description="Sobreventa",
                direction="bullish",
                source="indicator",
            ),
            SignalReason(
                factor="EMA_cross",
                value="20>50",
                contribution=0.3,
                weight=0.22,
                description="Cruce alcista",
                direction="bullish",
                source="indicator",
            ),
            SignalReason(
                factor="regime",
                value="weak_uptrend",
                contribution=0.2,
                weight=0.18,
                description="Regimen favorable",
                direction="bullish",
                source="regime",
            ),
        ],
    )


def test_explain_full_contains_buy_word_and_reasons() -> None:
    explainer = SignalExplainer()
    text = explainer.explain_full(_ensemble(SignalDirection.BUY))
    assert "COMPRAR" in text
    assert text.count("- ") >= 3


def test_notification_is_short() -> None:
    explainer = SignalExplainer()
    text = explainer.explain_notification(_ensemble(SignalDirection.BUY))
    assert len(text) < 140


def test_no_trade_reason_included() -> None:
    explainer = SignalExplainer()
    text = explainer.explain_no_trade("news_window_NFP")
    assert "news_window_NFP" in text


def test_horizon_render_helpers() -> None:
    assert _horizon_to_human("2h") == "2 horas"
    assert _horizon_to_human("1M") == "1 mes"
    assert _horizon_to_human("30m") == "30 minutos"
