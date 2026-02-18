from __future__ import annotations

from datetime import UTC, datetime, timedelta

from data.asset_types import AssetClass
from data.models import OHLCVBar
from data.validator import DataValidator


def _make_bar(start: datetime, close: float, high: float | None = None, low: float | None = None) -> OHLCVBar:
    return OHLCVBar(
        symbol="EURUSD",
        broker="mock",
        timeframe="M1",
        timestamp_open=start,
        timestamp_close=start + timedelta(minutes=1),
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=10,
        asset_class=AssetClass.FOREX,
        source="mock",
    )


def test_detects_gaps() -> None:
    validator = DataValidator()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = [_make_bar(base, 1.0), _make_bar(base + timedelta(minutes=2), 1.1)]

    report = validator.validate_series(bars, expected_timeframe="M1")

    assert report.missing_bars == 1


def test_detects_duplicates() -> None:
    validator = DataValidator()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = [_make_bar(base, 1.0), _make_bar(base, 1.1)]

    report = validator.validate_series(bars, expected_timeframe="M1")

    assert report.duplicate_bars >= 1


def test_detects_corrupt_bars() -> None:
    validator = DataValidator()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    valid = _make_bar(base, 1.0)
    corrupt = valid.model_copy(
        update={
            "timestamp_open": base + timedelta(minutes=1),
            "timestamp_close": base + timedelta(minutes=2),
            "high": 1.0,
            "low": 1.2,
        }
    )
    bars = [valid, corrupt]

    report = validator.validate_series(bars, expected_timeframe="M1")

    assert report.corrupt_bars >= 1


def test_detects_outliers() -> None:
    validator = DataValidator(outlier_std_threshold=1.5)
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = [_make_bar(base + timedelta(minutes=i), 1.0 + i * 0.001) for i in range(10)]
    bars.append(_make_bar(base + timedelta(minutes=10), 10.0))

    report = validator.validate_series(bars, expected_timeframe="M1")

    assert report.outlier_bars >= 1


def test_clean_series_quality_score_is_one() -> None:
    validator = DataValidator()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = [_make_bar(base + timedelta(minutes=i), 1.0 + i * 0.001) for i in range(5)]

    report = validator.validate_series(bars, expected_timeframe="M1")

    assert report.quality_score == 1.0


def test_fix_series_drop_removes_problematic_rows() -> None:
    validator = DataValidator()
    base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    valid = _make_bar(base, 1.0)
    invalid = valid.model_copy(
        update={
            "timestamp_open": base + timedelta(minutes=1),
            "timestamp_close": base + timedelta(minutes=2),
            "high": 0.9,
            "low": 1.2,
        }
    )
    fixed = validator.fix_series([valid, invalid], strategy="drop")

    assert len(fixed) == 1
    assert fixed[0].timestamp_open == valid.timestamp_open
