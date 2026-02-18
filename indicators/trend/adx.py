"""ADX trend-strength indicator."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_int
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class ADX(BaseIndicator):
    """Average Directional Index with DI+/DI-."""

    indicator_id = "ADX"

    def __init__(self, backend: IndicatorBackend | None = None, period: int = 14) -> None:
        self.backend = backend or IndicatorBackend()
        self.period = period

    @property
    def warmup_period(self) -> int:
        return self.period

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period = param_int(params, "period", self.period)
        if len(bars) < period:
            return empty_series(
                indicator_id=f"ADX_{period}",
                bars=bars,
                name="ADX",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period},
            )

        frame = self.to_dataframe(bars)
        high = frame["high"].to_numpy(dtype=float)
        low = frame["low"].to_numpy(dtype=float)
        close = frame["close"].to_numpy(dtype=float)
        adx, plus_di, minus_di = self.backend.adx(high, low, close, period)

        extras = []
        for idx in range(len(bars)):
            extras.append(
                {
                    "plus_di": float(plus_di[idx]) if np.isfinite(plus_di[idx]) else None,
                    "minus_di": float(minus_di[idx]) if np.isfinite(minus_di[idx]) else None,
                }
            )

        return build_indicator_series(
            indicator_id=f"ADX_{period}",
            bars=bars,
            values=adx,
            name="ADX",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period},
            extras=extras,
        )

    def is_trending(self, bars: list[OHLCVBar], threshold: float = 25.0) -> bool:
        series = self.compute(bars)
        if not series.values:
            return False
        value = series.values[-1].value
        return value is not None and value >= threshold

    def trend_strength(self, bars: list[OHLCVBar]) -> str:
        series = self.compute(bars)
        if not series.values:
            return "ranging"

        value = series.values[-1].value
        if value is None:
            return "ranging"
        if value >= 40:
            return "strong"
        if value >= 25:
            return "moderate"
        if value >= 20:
            return "weak"
        return "ranging"


__all__ = ["ADX"]
