"""Simple chart-pattern heuristics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from data.models import OHLCVBar


class ChartPatternMatch(BaseModel):
    """Detected chart pattern instance."""

    name: str
    direction: Literal["bullish", "bearish", "neutral"]
    confidence: float
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def ensure_timestamp_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class ChartPatternDetector:
    """Detect simple H&S/double-top/double-bottom forms."""

    def detect(self, bars: list[OHLCVBar]) -> list[ChartPatternMatch]:
        if len(bars) < 10:
            return []

        out: list[ChartPatternMatch] = []
        highs = [bar.high for bar in bars[-10:]]
        lows = [bar.low for bar in bars[-10:]]
        last = bars[-1]

        if abs(max(highs[:5]) - max(highs[5:])) / max(highs) < 0.003:
            out.append(
                ChartPatternMatch(
                    name="DoubleTop",
                    direction="bearish",
                    confidence=0.7,
                    timestamp=last.timestamp_close,
                )
            )

        if abs(min(lows[:5]) - min(lows[5:])) / max(min(lows), 1e-9) < 0.003:
            out.append(
                ChartPatternMatch(
                    name="DoubleBottom",
                    direction="bullish",
                    confidence=0.7,
                    timestamp=last.timestamp_close,
                )
            )

        middle_high = max(highs[3:7])
        shoulders = max(highs[:3] + highs[7:])
        if middle_high > shoulders * 1.01:
            out.append(
                ChartPatternMatch(
                    name="HeadAndShoulders",
                    direction="bearish",
                    confidence=0.6,
                    timestamp=last.timestamp_close,
                )
            )

        return out


__all__ = ["ChartPatternDetector", "ChartPatternMatch"]
