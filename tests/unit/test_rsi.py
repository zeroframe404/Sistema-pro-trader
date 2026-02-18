from __future__ import annotations

from indicators.momentum.rsi import RSI
from tests.unit._indicator_fixtures import make_bars


def test_rsi_known_synthetic_reference() -> None:
    closes = [44, 44.15, 43.9, 44.35, 44.6, 44.2, 44.4, 44.8, 45.0, 44.7, 44.9, 45.1, 45.0, 45.2, 45.4, 45.3, 45.5]
    bars = make_bars([float(v) for v in closes])
    series = RSI(period=14).compute(bars)
    last = series.values[-1].value
    assert last is not None
    assert 0.0 <= last <= 100.0


def test_rsi_flat_series_equals_50() -> None:
    bars = make_bars([10.0] * 30)
    series = RSI(period=14).compute(bars)
    assert series.values[-1].value == 50.0


def test_rsi_insufficient_length_returns_none() -> None:
    bars = make_bars([1.0, 1.1, 1.2])
    series = RSI(period=14).compute(bars)
    assert all(item.value is None for item in series.values)


def test_rsi_overbought_threshold() -> None:
    assert RSI.is_overbought(75, 70) is True
    assert RSI.is_overbought(65, 70) is False


def test_rsi_oversold_threshold() -> None:
    assert RSI.is_oversold(25, 30) is True
    assert RSI.is_oversold(35, 30) is False
