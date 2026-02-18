"""Chaikin Money Flow indicator."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class CMF(BaseIndicator):
    """Chaikin Money Flow."""

    indicator_id = "CMF"

    def __init__(self, backend: IndicatorBackend | None = None, period: int = 20) -> None:
        self.backend = backend or IndicatorBackend()
        self.period = period

    @property
    def warmup_period(self) -> int:
        return self.period

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period = int(params.get("period", self.period))
        if len(bars) < period:
            return empty_series(
                indicator_id=f"CMF_{period}",
                bars=bars,
                name="CMF",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period},
            )

        frame = self.to_dataframe(bars)
        high = frame["high"]
        low = frame["low"]
        close = frame["close"]
        volume = frame["volume"]

        denominator = (high - low).replace(0, np.nan)
        mfm = ((close - low) - (high - close)) / denominator
        mfv = mfm * volume
        cmf = mfv.rolling(period, min_periods=period).sum() / volume.rolling(
            period,
            min_periods=period,
        ).sum()

        return build_indicator_series(
            indicator_id=f"CMF_{period}",
            bars=bars,
            values=cmf.to_numpy(dtype=float),
            name="CMF",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period},
        )


__all__ = ["CMF"]
