from __future__ import annotations

import math

from indicators.trend.moving_averages import EMA, SMA, CrossDetector
from tests.unit._indicator_fixtures import make_bars


def test_sma_known_series() -> None:
    bars = make_bars([1, 2, 3, 4, 5])
    series = SMA(period=3).compute(bars)
    values = [item.value for item in series.values]

    assert values[0] is None
    assert values[1] is None
    assert values[2] == 2.0
    assert values[3] == 3.0
    assert values[4] == 4.0


def test_ema_close_to_reference() -> None:
    bars = make_bars([1, 2, 3, 4, 5, 6, 7])
    series = EMA(period=3).compute(bars)
    expected_last = 6.015625
    actual_last = series.values[-1].value
    assert actual_last is not None
    assert math.isclose(actual_last, expected_last, rel_tol=1e-3)


def test_ema_insufficient_bars_returns_none_values() -> None:
    bars = make_bars([1, 2])
    series = EMA(period=5).compute(bars)
    assert all(item.value is None for item in series.values)


def test_cross_detector_bullish_cross() -> None:
    fast = [1.0, 2.0]
    slow = [1.5, 1.8]
    assert CrossDetector.detect_cross(fast, slow) == "bullish"


def test_cross_detector_no_false_cross_on_flat_range() -> None:
    fast = [1.0, 1.0]
    slow = [1.0, 1.0]
    assert CrossDetector.detect_cross(fast, slow) is None
