"""Average True Range and volatility regime helper."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class ATR(BaseIndicator):
    """ATR with optional smoothing methods."""

    indicator_id = "ATR"

    def __init__(self, backend: IndicatorBackend | None = None, period: int = 14) -> None:
        self.backend = backend or IndicatorBackend()
        self.period = period

    @property
    def warmup_period(self) -> int:
        return self.period

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period = int(params.get("period", self.period))
        smoothing = str(params.get("smoothing", "wilder")).lower()

        if len(bars) < period:
            return empty_series(
                indicator_id=f"ATR_{period}",
                bars=bars,
                name="ATR",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period, "smoothing": smoothing},
            )

        frame = self.to_dataframe(bars)
        high = frame["high"].to_numpy(dtype=float)
        low = frame["low"].to_numpy(dtype=float)
        close = frame["close"].to_numpy(dtype=float)

        atr_values = self.backend.atr(high, low, close, period)
        if smoothing == "sma":
            tr = pd.Series(atr_values, dtype=float)
            atr_values = tr.rolling(period, min_periods=period).mean().to_numpy(dtype=float)

        atr_percent = np.where(close != 0, (atr_values / close) * 100.0, np.nan)
        extras = [
            {
                "atr_percent": float(atr_percent[idx]) if np.isfinite(atr_percent[idx]) else None,
            }
            for idx in range(len(bars))
        ]

        return build_indicator_series(
            indicator_id=f"ATR_{period}",
            bars=bars,
            values=atr_values,
            name="ATR",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period, "smoothing": smoothing},
            extras=extras,
        )

    def volatility_regime(self, bars: list[OHLCVBar], period: int = 14) -> str:
        series = self.compute(bars, period=period)
        valid = [item.value for item in series.values if item.value is not None]
        if not valid:
            return "low"

        latest = valid[-1]
        assert latest is not None
        p20 = float(np.percentile(valid, 20))
        p40 = float(np.percentile(valid, 40))
        p60 = float(np.percentile(valid, 60))
        p80 = float(np.percentile(valid, 80))

        if latest < p20:
            return "very_low"
        if latest < p40:
            return "low"
        if latest < p60:
            return "medium"
        if latest < p80:
            return "high"
        return "extreme"


__all__ = ["ATR"]
