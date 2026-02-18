"""Bollinger Bands indicator."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_float, param_int
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class BollingerBands(BaseIndicator):
    """Bollinger bands plus %B and bandwidth."""

    indicator_id = "BollingerBands"

    def __init__(
        self,
        backend: IndicatorBackend | None = None,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> None:
        self.backend = backend or IndicatorBackend()
        self.period = period
        self.std_dev = std_dev

    @property
    def warmup_period(self) -> int:
        return self.period

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period = param_int(params, "period", self.period)
        std_dev = param_float(params, "std_dev", self.std_dev)
        squeeze_lookback = param_int(params, "squeeze_lookback", 50)

        if len(bars) < period:
            return empty_series(
                indicator_id=f"BBANDS_{period}_{std_dev}",
                bars=bars,
                name="BollingerBands",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period, "std_dev": std_dev},
            )

        frame = self.to_dataframe(bars)
        close = frame["close"].to_numpy(dtype=float)
        upper, middle, lower = self.backend.bbands(close, period=period, std_dev=std_dev)

        extras = []
        band_width = np.where(middle != 0, (upper - lower) / middle, np.nan)
        percent_b = np.where((upper - lower) != 0, (close - lower) / (upper - lower), np.nan)

        for idx in range(len(bars)):
            squeeze = False
            if idx >= squeeze_lookback and np.isfinite(band_width[idx]):
                recent = band_width[idx - squeeze_lookback + 1 : idx + 1]
                finite_recent = recent[np.isfinite(recent)]
                if finite_recent.size > 0:
                    squeeze = float(band_width[idx]) <= float(np.min(finite_recent))

            extras.append(
                {
                    "upper": float(upper[idx]) if np.isfinite(upper[idx]) else None,
                    "middle": float(middle[idx]) if np.isfinite(middle[idx]) else None,
                    "lower": float(lower[idx]) if np.isfinite(lower[idx]) else None,
                    "percent_b": float(percent_b[idx]) if np.isfinite(percent_b[idx]) else None,
                    "bandwidth": float(band_width[idx]) if np.isfinite(band_width[idx]) else None,
                    "squeeze": squeeze,
                }
            )

        return build_indicator_series(
            indicator_id=f"BBANDS_{period}_{std_dev}",
            bars=bars,
            values=middle,
            name="BollingerBands",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period, "std_dev": std_dev, "squeeze_lookback": squeeze_lookback},
            extras=extras,
        )


__all__ = ["BollingerBands"]
