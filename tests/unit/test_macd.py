from __future__ import annotations

import math

import numpy as np

from indicators.indicator_backend import IndicatorBackend
from indicators.momentum.macd import MACD
from tests.unit._indicator_fixtures import make_bars


def test_macd_line_equals_ema_fast_minus_ema_slow() -> None:
    bars = make_bars([float(100 + i) for i in range(60)])
    series = MACD().compute(bars)

    backend = IndicatorBackend(preference="custom")
    closes = [bar.close for bar in bars]
    ema12 = backend.ema(close=np.array(closes, dtype=float), period=12)
    ema26 = backend.ema(close=np.array(closes, dtype=float), period=26)
    expected = ema12[-1] - ema26[-1]

    actual = series.values[-1].extra["macd"]
    assert actual is not None
    assert math.isclose(float(actual), float(expected), rel_tol=1e-6)


def test_macd_signal_histogram_relationship() -> None:
    bars = make_bars([float(50 + i * 0.5) for i in range(70)])
    series = MACD().compute(bars)
    last = series.values[-1].extra
    assert last["macd"] is not None
    assert last["signal"] is not None
    assert last["histogram"] is not None
    assert math.isclose(
        float(last["histogram"]),
        float(last["macd"]) - float(last["signal"]),
        rel_tol=1e-6,
    )


def test_macd_warmup_returns_none() -> None:
    bars = make_bars([float(1 + i) for i in range(20)])
    series = MACD().compute(bars)
    assert all(item.value is None for item in series.values)


def test_macd_detects_bullish_cross() -> None:
    closes = [10.0] * 40 + [10.1, 10.3, 10.7, 11.2, 11.8]
    series = MACD().compute(make_bars(closes))
    crosses = [item.extra.get("cross") for item in series.values if item.extra.get("cross")]
    assert "bullish" in crosses
