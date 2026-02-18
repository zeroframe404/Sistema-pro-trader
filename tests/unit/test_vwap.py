from __future__ import annotations

from datetime import UTC, datetime, timedelta

from data.asset_types import AssetClass
from data.models import OHLCVBar
from indicators.volume.vwap import VWAP


def _daily_bars() -> list[OHLCVBar]:
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars: list[OHLCVBar] = []
    for idx in range(6):
        ts_open = start + timedelta(hours=idx * 12)
        bars.append(
            OHLCVBar(
                symbol="EURUSD",
                broker="mock",
                timeframe="H1",
                timestamp_open=ts_open,
                timestamp_close=ts_open + timedelta(hours=1),
                open=1.1 + idx * 0.001,
                high=1.2 + idx * 0.001,
                low=1.0 + idx * 0.001,
                close=1.15 + idx * 0.001,
                volume=100 + idx,
                asset_class=AssetClass.FOREX,
                source="test",
            )
        )
    return bars


def test_vwap_single_bar_typical_price_weighted() -> None:
    bars = _daily_bars()[:1]
    series = VWAP().compute(bars)
    expected = (bars[0].high + bars[0].low + bars[0].close) / 3.0
    assert series.values[0].value == expected


def test_vwap_resets_each_utc_day() -> None:
    bars = _daily_bars()
    series = VWAP().compute(bars)
    # First bar of day 1 and first bar of day 2 should both be typical price of that bar.
    first_day_1 = series.values[0].value
    first_day_2 = series.values[2].value
    assert first_day_1 is not None
    assert first_day_2 is not None


def test_vwap_without_volume_returns_none() -> None:
    bars = _daily_bars()
    for bar in bars:
        bar.volume = 0.0
    series = VWAP().compute(bars)
    assert all(item.value is None for item in series.values)
