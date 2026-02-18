"""Candlestick pattern detector."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class PatternMatch(BaseModel):
    """Detected candlestick pattern."""

    name: str
    timestamp: datetime
    direction: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)
    bar_index: int

    @field_validator("timestamp")
    @classmethod
    def ensure_timestamp_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class CandlestickPatternDetector:
    """Rule-based detector for common candlestick patterns."""

    def detect_all(self, bars: list[OHLCVBar]) -> list[PatternMatch]:
        if len(bars) < 3:
            return []

        out: list[PatternMatch] = []
        for idx in range(1, len(bars)):
            current = bars[idx]
            previous = bars[idx - 1]

            if self._is_doji(current):
                out.append(self._match("Doji", current, "neutral", 0.6, idx))
            if self._is_hammer(current):
                out.append(self._match("Hammer", current, "bullish", 0.8, idx))
            if self._is_shooting_star(current):
                out.append(self._match("ShootingStar", current, "bearish", 0.8, idx))
            if self._is_bullish_engulfing(previous, current):
                out.append(self._match("BullishEngulfing", current, "bullish", 0.85, idx))
            if self._is_bearish_engulfing(previous, current):
                out.append(self._match("BearishEngulfing", current, "bearish", 0.85, idx))

        return out

    @staticmethod
    def _match(
        name: str,
        bar: OHLCVBar,
        direction: Literal["bullish", "bearish", "neutral"],
        confidence: float,
        idx: int,
    ) -> PatternMatch:
        return PatternMatch(
            name=name,
            timestamp=bar.timestamp_close,
            direction=direction,
            confidence=confidence,
            bar_index=idx,
        )

    @staticmethod
    def _is_doji(bar: OHLCVBar) -> bool:
        candle_range = bar.high - bar.low
        if candle_range <= 0:
            return False
        body = abs(bar.open - bar.close)
        return body <= (candle_range * 0.05)

    @staticmethod
    def _is_hammer(bar: OHLCVBar) -> bool:
        body = abs(bar.open - bar.close)
        lower_shadow = min(bar.open, bar.close) - bar.low
        upper_shadow = bar.high - max(bar.open, bar.close)
        return body > 0 and lower_shadow >= (2 * body) and upper_shadow <= body

    @staticmethod
    def _is_shooting_star(bar: OHLCVBar) -> bool:
        body = abs(bar.open - bar.close)
        upper_shadow = bar.high - max(bar.open, bar.close)
        lower_shadow = min(bar.open, bar.close) - bar.low
        return body > 0 and upper_shadow >= (2 * body) and lower_shadow <= body

    @staticmethod
    def _is_bullish_engulfing(prev: OHLCVBar, cur: OHLCVBar) -> bool:
        prev_bearish = prev.close < prev.open
        cur_bullish = cur.close > cur.open
        return (
            prev_bearish
            and cur_bullish
            and cur.open <= prev.close
            and cur.close >= prev.open
        )

    @staticmethod
    def _is_bearish_engulfing(prev: OHLCVBar, cur: OHLCVBar) -> bool:
        prev_bullish = prev.close > prev.open
        cur_bearish = cur.close < cur.open
        return (
            prev_bullish
            and cur_bearish
            and cur.open >= prev.close
            and cur.close <= prev.open
        )


class CandlestickPatterns(BaseIndicator):
    """Indicator wrapper around candlestick pattern detection."""

    indicator_id = "CandlestickPatterns"

    def __init__(self, backend: IndicatorBackend | None = None) -> None:
        self.backend = backend or IndicatorBackend()
        self.detector = CandlestickPatternDetector()

    @property
    def warmup_period(self) -> int:
        return 3

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        _ = params
        if len(bars) < 3:
            return empty_series(
                indicator_id="CandlestickPatterns",
                bars=bars,
                name="CandlestickPatterns",
                warmup_period=self.warmup_period,
                backend_used="custom",
                parameters={},
            )

        matches = self.detector.detect_all(bars)
        by_index: dict[int, list[PatternMatch]] = {}
        for match in matches:
            by_index.setdefault(match.bar_index, []).append(match)

        values = []
        extras = []
        for idx, _bar in enumerate(bars):
            row_matches = by_index.get(idx, [])
            confidence = max((item.confidence for item in row_matches), default=0.0)
            values.append(confidence)
            extras.append(
                {
                    "patterns": [item.model_dump(mode="python") for item in row_matches],
                }
            )

        import numpy as np

        return build_indicator_series(
            indicator_id="CandlestickPatterns",
            bars=bars,
            values=np.asarray(values, dtype=float),
            name="CandlestickPatterns",
            warmup_period=self.warmup_period,
            backend_used="custom",
            parameters={},
            extras=extras,
        )


__all__ = ["PatternMatch", "CandlestickPatternDetector", "CandlestickPatterns"]
