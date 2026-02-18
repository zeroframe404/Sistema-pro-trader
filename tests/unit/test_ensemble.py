from __future__ import annotations

from signals.ensemble import SignalEnsemble
from signals.signal_models import SignalDirection
from tests.unit._signal_fixtures import make_regime, make_signal


def test_all_buy_results_buy() -> None:
    ensemble = SignalEnsemble()
    signals = [make_signal(direction=SignalDirection.BUY, confidence=0.7) for _ in range(3)]
    result = ensemble.combine(signals, regime=make_regime())
    assert result.final_direction == SignalDirection.BUY


def test_equal_buy_sell_results_wait() -> None:
    ensemble = SignalEnsemble()
    signals = [
        make_signal(direction=SignalDirection.BUY, confidence=0.7),
        make_signal(direction=SignalDirection.BUY, confidence=0.6),
        make_signal(direction=SignalDirection.SELL, confidence=0.7),
        make_signal(direction=SignalDirection.SELL, confidence=0.6),
    ]
    result = ensemble.combine(signals, regime=make_regime())
    assert result.final_direction == SignalDirection.WAIT


def test_higher_confidence_wins() -> None:
    ensemble = SignalEnsemble()
    signals = [
        make_signal(direction=SignalDirection.BUY, confidence=0.95),
        make_signal(direction=SignalDirection.SELL, confidence=0.30),
    ]
    result = ensemble.combine(signals, regime=make_regime(), method="best_confidence")
    assert result.final_direction == SignalDirection.BUY


def test_no_signals_no_trade() -> None:
    ensemble = SignalEnsemble()
    result = ensemble.combine([], regime=make_regime())
    assert result.final_direction == SignalDirection.NO_TRADE


def test_all_wait_results_wait() -> None:
    ensemble = SignalEnsemble()
    signals = [make_signal(direction=SignalDirection.WAIT, confidence=0.3) for _ in range(2)]
    result = ensemble.combine(signals, regime=make_regime())
    assert result.final_direction == SignalDirection.WAIT


def test_agreement_scores_for_unanimous_and_split() -> None:
    ensemble = SignalEnsemble()
    unanimous = [make_signal(direction=SignalDirection.BUY, confidence=0.7) for _ in range(3)]
    result_unanimous = ensemble.combine(unanimous, regime=make_regime())
    assert result_unanimous.agreement_score == 1.0

    split = [
        make_signal(direction=SignalDirection.BUY, confidence=0.7),
        make_signal(direction=SignalDirection.SELL, confidence=0.7),
    ]
    result_split = ensemble.combine(split, regime=make_regime())
    assert result_split.agreement_score == 0.5


def test_regime_weighted_prefers_regime_compatible_strategy() -> None:
    ensemble = SignalEnsemble(strategy_weights={"mean_reversion": 0.4, "trend_following": 0.3})
    regime = make_regime()
    regime.recommended_strategies = ["mean_reversion"]
    signals = [
        make_signal(direction=SignalDirection.BUY, confidence=0.6, strategy_id="mean_reversion"),
        make_signal(direction=SignalDirection.SELL, confidence=0.6, strategy_id="trend_following"),
    ]
    result = ensemble.combine(signals, regime=regime, method="regime_weighted")
    assert result.final_direction == SignalDirection.BUY
