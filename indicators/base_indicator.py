"""Base interface for all indicators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC

import pandas as pd

from data.models import OHLCVBar
from indicators.indicator_result import IndicatorSeries, IndicatorValue


class BaseIndicator(ABC):
    """Stateless indicator contract."""

    indicator_id: str = "BASE"
    version: str = "1.0.0"

    @property
    @abstractmethod
    def warmup_period(self) -> int:
        """Minimum bars required for valid output."""

    @abstractmethod
    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        """Compute indicator values for the full bar list."""

    def compute_last(self, bars: list[OHLCVBar], **params: object) -> IndicatorValue:
        """Compute only the latest indicator value."""

        result = self.compute(bars, **params)
        if not result.values:
            raise ValueError("compute() returned no values")
        return result.values[-1]

    def validate_bars(self, bars: list[OHLCVBar]) -> None:
        """Validate chronological ordering and timestamp consistency."""

        if not bars:
            return

        for idx in range(1, len(bars)):
            if bars[idx].timestamp_open < bars[idx - 1].timestamp_open:
                raise ValueError("bars must be sorted by timestamp_open ascending")

    def to_dataframe(self, bars: list[OHLCVBar]) -> pd.DataFrame:
        """Convert OHLCV bars into a pandas DataFrame."""

        self.validate_bars(bars)
        rows = [
            {
                "timestamp_open": bar.timestamp_open.astimezone(UTC),
                "timestamp_close": bar.timestamp_close.astimezone(UTC),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "symbol": bar.symbol,
                "timeframe": bar.timeframe,
            }
            for bar in bars
        ]
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values("timestamp_open").reset_index(drop=True)
        return frame


__all__ = ["BaseIndicator"]
