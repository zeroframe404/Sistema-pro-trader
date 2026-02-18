"""Ichimoku cloud indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class Ichimoku(BaseIndicator):
    """Ichimoku Cloud full component calculation."""

    indicator_id = "Ichimoku"

    def __init__(self, backend: IndicatorBackend | None = None) -> None:
        self.backend = backend or IndicatorBackend()

    @property
    def warmup_period(self) -> int:
        return 52

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        _ = params
        if len(bars) < self.warmup_period:
            return empty_series(
                indicator_id="Ichimoku_9_26_52",
                bars=bars,
                name="Ichimoku",
                warmup_period=self.warmup_period,
                backend_used=self.backend.backend_name,
                parameters={},
            )

        frame = self.to_dataframe(bars)
        high = pd.Series(frame["high"].to_numpy(dtype=float), dtype=float)
        low = pd.Series(frame["low"].to_numpy(dtype=float), dtype=float)
        close = pd.Series(frame["close"].to_numpy(dtype=float), dtype=float)

        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2.0
        kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2.0
        senkou_a = ((tenkan + kijun) / 2.0).shift(26)
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2.0).shift(26)
        chikou = close.shift(-26)

        extras = []
        signal = []
        values = []
        for idx in range(len(bars)):
            t = float(tenkan.iloc[idx]) if np.isfinite(tenkan.iloc[idx]) else None
            k = float(kijun.iloc[idx]) if np.isfinite(kijun.iloc[idx]) else None
            sa = float(senkou_a.iloc[idx]) if np.isfinite(senkou_a.iloc[idx]) else None
            sb = float(senkou_b.iloc[idx]) if np.isfinite(senkou_b.iloc[idx]) else None
            ck = float(chikou.iloc[idx]) if np.isfinite(chikou.iloc[idx]) else None
            cloud_signal = self.get_cloud_signal(
                close=float(close.iloc[idx]),
                senkou_a=sa,
                senkou_b=sb,
            )
            signal.append(cloud_signal)
            values.append(float((t + k) / 2.0) if t is not None and k is not None else np.nan)
            extras.append(
                {
                    "tenkan": t,
                    "kijun": k,
                    "senkou_a": sa,
                    "senkou_b": sb,
                    "chikou": ck,
                    "cloud_signal": cloud_signal,
                }
            )

        return build_indicator_series(
            indicator_id="Ichimoku_9_26_52",
            bars=bars,
            values=np.asarray(values, dtype=float),
            name="Ichimoku",
            warmup_period=self.warmup_period,
            backend_used=self.backend.backend_name,
            parameters={},
            extras=extras,
        )

    @staticmethod
    def get_cloud_signal(close: float, senkou_a: float | None, senkou_b: float | None) -> str:
        if senkou_a is None or senkou_b is None:
            return "neutral"
        top = max(senkou_a, senkou_b)
        bottom = min(senkou_a, senkou_b)
        if close > top:
            return "bullish"
        if close < bottom:
            return "bearish"
        return "neutral"


__all__ = ["Ichimoku"]
