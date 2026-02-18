"""Money Flow Index."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_int
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class MFI(BaseIndicator):
    """Money Flow Index indicator."""

    indicator_id = "MFI"

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
                indicator_id=f"MFI_{period}",
                bars=bars,
                name="MFI",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period},
            )

        frame = self.to_dataframe(bars)
        typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3.0
        raw_flow = typical_price * frame["volume"]

        positive = raw_flow.where(typical_price.diff() > 0, 0.0)
        negative = raw_flow.where(typical_price.diff() < 0, 0.0).abs()

        pos_sum = positive.rolling(period, min_periods=period).sum()
        neg_sum = negative.rolling(period, min_periods=period).sum()
        ratio = pos_sum / neg_sum.replace(0, np.nan)
        mfi = 100.0 - (100.0 / (1.0 + ratio))

        return build_indicator_series(
            indicator_id=f"MFI_{period}",
            bars=bars,
            values=mfi.to_numpy(dtype=float),
            name="MFI",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period},
        )


__all__ = ["MFI"]
