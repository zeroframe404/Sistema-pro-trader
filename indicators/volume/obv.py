"""On-Balance Volume indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class OBV(BaseIndicator):
    """Cumulative OBV."""

    indicator_id = "OBV"

    def __init__(self, backend: IndicatorBackend | None = None) -> None:
        self.backend = backend or IndicatorBackend()

    @property
    def warmup_period(self) -> int:
        return 1

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        _ = params
        if not bars:
            return empty_series(
                indicator_id="OBV",
                bars=bars,
                name="OBV",
                warmup_period=1,
                backend_used=self.backend.backend_name,
                parameters={},
            )

        frame = self.to_dataframe(bars)
        close = pd.Series(frame["close"].to_numpy(dtype=float), dtype=float)
        volume = pd.Series(frame["volume"].to_numpy(dtype=float), dtype=float)
        direction = np.sign(close.diff().fillna(0.0))
        obv = (direction * volume).cumsum()

        return build_indicator_series(
            indicator_id="OBV",
            bars=bars,
            values=obv.to_numpy(dtype=float),
            name="OBV",
            warmup_period=1,
            backend_used=self.backend.backend_name,
            parameters={},
        )


__all__ = ["OBV"]
