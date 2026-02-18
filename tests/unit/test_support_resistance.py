from __future__ import annotations

from indicators.patterns.support_resistance import SupportResistanceDetector
from tests.unit._indicator_fixtures import make_bars


def test_detect_resistance_on_clear_peak() -> None:
    closes = [1.0, 1.1, 1.3, 1.1, 1.0, 1.05, 1.2, 1.05, 1.0]
    levels = SupportResistanceDetector().detect_levels(make_bars(closes), min_touches=1)
    assert any(level.type == "resistance" for level in levels)


def test_detect_support_on_clear_valley() -> None:
    closes = [1.2, 1.1, 0.9, 1.1, 1.2, 1.15, 0.95, 1.1, 1.2]
    levels = SupportResistanceDetector().detect_levels(make_bars(closes), min_touches=1)
    assert any(level.type == "support" for level in levels)


def test_get_nearest_level_returns_closest() -> None:
    closes = [1.0, 1.2, 1.0, 1.2, 1.0, 1.2, 1.0]
    detector = SupportResistanceDetector()
    level = detector.get_nearest_level(make_bars(closes), price=1.1)
    assert level is not None


def test_no_level_detected_on_linear_series() -> None:
    closes = [1.0 + i * 0.01 for i in range(20)]
    levels = SupportResistanceDetector().detect_levels(make_bars(closes), min_touches=2)
    assert levels == []
