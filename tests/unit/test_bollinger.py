from __future__ import annotations

import math

from indicators.volatility.bollinger_bands import BollingerBands
from tests.unit._indicator_fixtures import make_bars


def test_bollinger_middle_band_is_sma() -> None:
    bars = make_bars([float(i) for i in range(1, 40)])
    series = BollingerBands(period=20, std_dev=2.0).compute(bars)
    last = series.values[-1]
    middle = last.extra["middle"]
    assert middle is not None
    expected = sum(range(20, 40)) / 20
    assert math.isclose(float(middle), expected, rel_tol=1e-6)


def test_bollinger_upper_lower_definition() -> None:
    bars = make_bars([10.0 + (i * 0.1) for i in range(60)])
    series = BollingerBands(period=20, std_dev=2.0).compute(bars)
    last = series.values[-1].extra
    assert last["upper"] is not None
    assert last["lower"] is not None
    assert float(last["upper"]) >= float(last["middle"])
    assert float(last["lower"]) <= float(last["middle"])


def test_bollinger_percent_b_bounds() -> None:
    bars = make_bars([1 + (i % 3) * 0.01 for i in range(80)])
    series = BollingerBands(period=20, std_dev=2.0).compute(bars)
    values = [item.extra.get("percent_b") for item in series.values if item.extra.get("percent_b") is not None]
    assert values
    assert all(-1.0 <= float(v) <= 2.0 for v in values)


def test_bollinger_squeeze_flag_present() -> None:
    bars = make_bars([1.0 + (i * 0.001) for i in range(120)])
    series = BollingerBands(period=20, std_dev=2.0).compute(bars, squeeze_lookback=50)
    assert any(isinstance(item.extra.get("squeeze"), bool) for item in series.values)
