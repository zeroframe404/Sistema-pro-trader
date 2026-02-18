"""Moving-average indicators and cross detection."""

from __future__ import annotations

from math import sqrt

import numpy as np
import pandas as pd

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, get_price_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class _MAIndicator(BaseIndicator):
    """Shared moving-average behavior."""

    indicator_id = "MA"

    def __init__(
        self,
        backend: IndicatorBackend | None = None,
        period: int = 20,
        price_field: str = "close",
    ) -> None:
        self.backend = backend or IndicatorBackend()
        self.period = period
        self.price_field = price_field

    @property
    def warmup_period(self) -> int:
        return self.period

    def _resolve(self, **params: object) -> tuple[int, str]:
        period = int(params.get("period", self.period))
        price_field = str(params.get("price_field", self.price_field))
        if period <= 0:
            raise ValueError("period must be > 0")
        return period, price_field


class SMA(_MAIndicator):
    indicator_id = "SMA"

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period, price_field = self._resolve(**params)
        if not bars:
            return empty_series(
                indicator_id=f"SMA_{period}",
                bars=bars,
                name="SMA",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period, "price_field": price_field},
            )

        frame = self.to_dataframe(bars)
        close = get_price_series(frame, price_field)
        values = self.backend.sma(close, period)
        return build_indicator_series(
            indicator_id=f"SMA_{period}",
            bars=bars,
            values=values,
            name="SMA",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period, "price_field": price_field},
        )


class EMA(_MAIndicator):
    indicator_id = "EMA"

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period, price_field = self._resolve(**params)
        if not bars:
            return empty_series(
                indicator_id=f"EMA_{period}",
                bars=bars,
                name="EMA",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period, "price_field": price_field},
            )

        frame = self.to_dataframe(bars)
        close = get_price_series(frame, price_field)
        values = self.backend.ema(close, period)
        return build_indicator_series(
            indicator_id=f"EMA_{period}",
            bars=bars,
            values=values,
            name="EMA",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period, "price_field": price_field},
        )


class WMA(_MAIndicator):
    indicator_id = "WMA"

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period, price_field = self._resolve(**params)
        if len(bars) < period:
            return empty_series(
                indicator_id=f"WMA_{period}",
                bars=bars,
                name="WMA",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period, "price_field": price_field},
            )

        frame = self.to_dataframe(bars)
        close = pd.Series(get_price_series(frame, price_field), dtype=float)
        weights = np.arange(1, period + 1, dtype=float)
        denominator = float(np.sum(weights))
        values = close.rolling(period).apply(
            lambda arr: float(np.dot(arr, weights) / denominator),
            raw=True,
        )
        return build_indicator_series(
            indicator_id=f"WMA_{period}",
            bars=bars,
            values=values.to_numpy(dtype=float),
            name="WMA",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period, "price_field": price_field},
        )


class DEMA(_MAIndicator):
    indicator_id = "DEMA"

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period, price_field = self._resolve(**params)
        if not bars:
            return empty_series(
                indicator_id=f"DEMA_{period}",
                bars=bars,
                name="DEMA",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period, "price_field": price_field},
            )

        frame = self.to_dataframe(bars)
        close = get_price_series(frame, price_field)
        ema1 = self.backend.ema(close, period)
        ema2 = self.backend.ema(ema1, period)
        values = (2.0 * ema1) - ema2
        return build_indicator_series(
            indicator_id=f"DEMA_{period}",
            bars=bars,
            values=values,
            name="DEMA",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period, "price_field": price_field},
        )


class TEMA(_MAIndicator):
    indicator_id = "TEMA"

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period, price_field = self._resolve(**params)
        if not bars:
            return empty_series(
                indicator_id=f"TEMA_{period}",
                bars=bars,
                name="TEMA",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period, "price_field": price_field},
            )

        frame = self.to_dataframe(bars)
        close = get_price_series(frame, price_field)
        ema1 = self.backend.ema(close, period)
        ema2 = self.backend.ema(ema1, period)
        ema3 = self.backend.ema(ema2, period)
        values = (3.0 * ema1) - (3.0 * ema2) + ema3
        return build_indicator_series(
            indicator_id=f"TEMA_{period}",
            bars=bars,
            values=values,
            name="TEMA",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period, "price_field": price_field},
        )


class HMA(_MAIndicator):
    indicator_id = "HMA"

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period, price_field = self._resolve(**params)
        if len(bars) < period:
            return empty_series(
                indicator_id=f"HMA_{period}",
                bars=bars,
                name="HMA",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period, "price_field": price_field},
            )

        frame = self.to_dataframe(bars)
        close = pd.Series(get_price_series(frame, price_field), dtype=float)

        def wma(series: pd.Series, length: int) -> pd.Series:
            weights = np.arange(1, length + 1, dtype=float)
            denominator = float(np.sum(weights))
            return series.rolling(length).apply(
                lambda arr: float(np.dot(arr, weights) / denominator),
                raw=True,
            )

        half = max(1, period // 2)
        root = max(1, int(sqrt(period)))
        wma_half = wma(close, half)
        wma_full = wma(close, period)
        hull = wma((2.0 * wma_half) - wma_full, root)
        return build_indicator_series(
            indicator_id=f"HMA_{period}",
            bars=bars,
            values=hull.to_numpy(dtype=float),
            name="HMA",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period, "price_field": price_field},
        )


class CrossDetector:
    """Detect bullish/bearish moving-average crosses."""

    @staticmethod
    def detect_cross(
        fast_values: list[float | None],
        slow_values: list[float | None],
    ) -> str | None:
        if len(fast_values) < 2 or len(slow_values) < 2:
            return None

        f_prev, f_curr = fast_values[-2], fast_values[-1]
        s_prev, s_curr = slow_values[-2], slow_values[-1]
        if None in {f_prev, f_curr, s_prev, s_curr}:
            return None

        assert f_prev is not None
        assert f_curr is not None
        assert s_prev is not None
        assert s_curr is not None

        if f_prev <= s_prev and f_curr > s_curr:
            return "bullish"
        if f_prev >= s_prev and f_curr < s_curr:
            return "bearish"
        return None

    @staticmethod
    def detect_cross_from_series(fast: IndicatorSeries, slow: IndicatorSeries) -> str | None:
        return CrossDetector.detect_cross(
            [item.value for item in fast.values],
            [item.value for item in slow.values],
        )


__all__ = [
    "SMA",
    "EMA",
    "WMA",
    "DEMA",
    "TEMA",
    "HMA",
    "CrossDetector",
]
