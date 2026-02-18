from __future__ import annotations

from indicators.volatility.atr import ATR
from tests.unit._indicator_fixtures import make_bars


def test_atr_positive_values() -> None:
    bars = make_bars([1.0 + i * 0.01 for i in range(60)])
    series = ATR(period=14).compute(bars)
    valid = [item.value for item in series.values if item.value is not None]
    assert valid
    assert all(value > 0 for value in valid)


def test_volatility_regime_low_percentile() -> None:
    bars = make_bars([1.0 + ((-1) ** i) * 0.001 for i in range(200)])
    regime = ATR(period=14).volatility_regime(bars)
    assert regime in {"very_low", "low", "medium", "high", "extreme"}


def test_volatility_regime_extreme_percentile() -> None:
    closes = [1.0 + (i * 0.001) for i in range(150)] + [2.0, 2.5, 3.0, 3.5, 4.0]
    bars = make_bars(closes)
    regime = ATR(period=14).volatility_regime(bars)
    assert regime in {"high", "extreme"}
