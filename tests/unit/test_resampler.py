from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data.asset_types import AssetClass
from data.models import OHLCVBar, Tick
from data.resampler import Resampler


def _tick(ts: datetime, price: float, volume: float) -> Tick:
    return Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=ts,
        bid=price - 0.0001,
        ask=price + 0.0001,
        last=price,
        volume=volume,
        spread=0.0002,
        asset_class=AssetClass.FOREX,
        source="mock",
    )


def _bar(ts: datetime, close: float) -> OHLCVBar:
    return OHLCVBar(
        symbol="EURUSD",
        broker="mock",
        timeframe="M1",
        timestamp_open=ts,
        timestamp_close=ts + timedelta(minutes=1),
        open=close,
        high=close + 0.001,
        low=close - 0.001,
        close=close,
        volume=10,
        asset_class=AssetClass.FOREX,
        source="mock",
    )


def test_ticks_to_m1_open_close_are_first_last() -> None:
    resampler = Resampler()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    ticks = [_tick(base + timedelta(seconds=5), 1.1, 1), _tick(base + timedelta(seconds=50), 1.2, 1)]

    bars = resampler.ticks_to_ohlcv(ticks, timeframe="M1")

    assert len(bars) == 1
    assert bars[0].open == 1.1
    assert bars[0].close == 1.2


def test_ticks_to_m1_volume_sum() -> None:
    resampler = Resampler()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    ticks = [_tick(base + timedelta(seconds=5), 1.1, 1.5), _tick(base + timedelta(seconds=15), 1.2, 2.0)]

    bars = resampler.ticks_to_ohlcv(ticks, timeframe="M1")

    assert bars[0].volume == 3.5


def test_m1_to_h1_generates_one_bar_per_sixty() -> None:
    resampler = Resampler()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = [_bar(base + timedelta(minutes=i), 1.0 + i * 0.001) for i in range(60)]

    result = resampler.resample_ohlcv(bars, source_timeframe="M1", target_timeframe="H1")

    assert len(result) == 1


def test_m1_to_h1_high_low_correct() -> None:
    resampler = Resampler()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = [_bar(base + timedelta(minutes=i), 1.0 + i * 0.001) for i in range(60)]

    result = resampler.resample_ohlcv(bars, source_timeframe="M1", target_timeframe="H1")

    assert result[0].high == max(item.high for item in bars)
    assert result[0].low == min(item.low for item in bars)


def test_no_ticks_no_ghost_bar() -> None:
    resampler = Resampler()
    assert resampler.ticks_to_ohlcv([], timeframe="M1") == []


def test_downsampling_raises_error() -> None:
    resampler = Resampler()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    h1_bar = OHLCVBar(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        timestamp_open=base,
        timestamp_close=base + timedelta(hours=1),
        open=1.0,
        high=1.2,
        low=0.9,
        close=1.1,
        volume=100,
        asset_class=AssetClass.FOREX,
        source="mock",
    )

    with pytest.raises(ValueError):
        resampler.resample_ohlcv([h1_bar], source_timeframe="H1", target_timeframe="M1")
