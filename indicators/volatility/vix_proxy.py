"""VIX proxy based on realized volatility."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class VIXProxy(BaseIndicator):
    """Annualized realized volatility proxy."""

    indicator_id = "VIXProxy"

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
                indicator_id=f"VIXProxy_{period}",
                bars=bars,
                name="VIXProxy",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period},
            )

        frame = self.to_dataframe(bars)
        close = pd.Series(frame["close"].to_numpy(dtype=float), dtype=float)
        log_returns = np.log(close / close.shift(1))
        realized = log_returns.rolling(period, min_periods=period).std(ddof=0) * np.sqrt(252.0) * 100.0

        return build_indicator_series(
            indicator_id=f"VIXProxy_{period}",
            bars=bars,
            values=realized.to_numpy(dtype=float),
            name="VIXProxy",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period},
        )


__all__ = ["VIXProxy"]
