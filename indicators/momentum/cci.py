"""Commodity Channel Index."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_int
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class CCI(BaseIndicator):
    """Commodity Channel Index indicator."""

    indicator_id = "CCI"

    def __init__(self, backend: IndicatorBackend | None = None, period: int = 20) -> None:
        self.backend = backend or IndicatorBackend()
        self.period = period

    @property
    def warmup_period(self) -> int:
        return self.period

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period = param_int(params, "period", self.period)
        if len(bars) < period:
            return empty_series(
                indicator_id=f"CCI_{period}",
                bars=bars,
                name="CCI",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period},
            )

        frame = self.to_dataframe(bars)
        tp = (frame["high"] + frame["low"] + frame["close"]) / 3.0
        sma = tp.rolling(period, min_periods=period).mean()
        mad = tp.rolling(period, min_periods=period).apply(
            lambda arr: float(np.mean(np.abs(arr - np.mean(arr)))),
            raw=True,
        )
        cci = (tp - sma) / (0.015 * mad)

        return build_indicator_series(
            indicator_id=f"CCI_{period}",
            bars=bars,
            values=cci.to_numpy(dtype=float),
            name="CCI",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period},
        )


__all__ = ["CCI"]
