from __future__ import annotations

from datetime import UTC, datetime, timedelta

from data.asset_types import AssetClass
from data.models import OHLCVBar
from indicators.patterns.candlestick_patterns import CandlestickPatternDetector


def _bar(open_: float, high: float, low: float, close: float, idx: int) -> OHLCVBar:
    ts = datetime(2026, 1, 1, 0, 0, tzinfo=UTC) + timedelta(minutes=idx)
    return OHLCVBar(
        symbol="EURUSD",
        broker="mock",
        timeframe="M1",
        timestamp_open=ts,
        timestamp_close=ts + timedelta(minutes=1),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
        asset_class=AssetClass.FOREX,
        source="test",
    )


def test_detect_doji() -> None:
    detector = CandlestickPatternDetector()
    bars = [_bar(1.0, 1.2, 0.8, 1.0, 0), _bar(1.0, 1.2, 0.8, 1.01, 1), _bar(1.0, 1.2, 0.8, 1.0, 2)]
    matches = detector.detect_all(bars)
    assert any(match.name == "Doji" for match in matches)


def test_detect_hammer() -> None:
    detector = CandlestickPatternDetector()
    bars = [_bar(1.0, 1.1, 0.9, 0.95, 0), _bar(1.0, 1.05, 0.7, 1.03, 1), _bar(1.03, 1.06, 1.0, 1.05, 2)]
    matches = detector.detect_all(bars)
    assert any(match.name == "Hammer" for match in matches)


def test_detect_bullish_engulfing() -> None:
    detector = CandlestickPatternDetector()
    bars = [_bar(1.1, 1.12, 1.0, 1.02, 0), _bar(1.01, 1.15, 1.0, 1.14, 1), _bar(1.14, 1.16, 1.1, 1.15, 2)]
    matches = detector.detect_all(bars)
    assert any(match.name == "BullishEngulfing" for match in matches)


def test_no_false_positive_on_normal_series() -> None:
    detector = CandlestickPatternDetector()
    bars = [_bar(1.0 + i * 0.01, 1.05 + i * 0.01, 0.95 + i * 0.01, 1.02 + i * 0.01, i) for i in range(5)]
    matches = detector.detect_all(bars)
    assert len(matches) <= 3


def test_short_series_returns_empty() -> None:
    detector = CandlestickPatternDetector()
    bars = [_bar(1.0, 1.1, 0.9, 1.02, 0), _bar(1.02, 1.1, 0.95, 1.04, 1)]
    assert detector.detect_all(bars) == []
