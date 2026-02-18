"""SuperTrend indicator implementation."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_float, param_int
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class SuperTrend(BaseIndicator):
    """ATR-based SuperTrend with direction and crossover signal."""

    indicator_id = "SuperTrend"

    def __init__(
        self,
        backend: IndicatorBackend | None = None,
        atr_period: int = 10,
        multiplier: float = 3.0,
    ) -> None:
        self.backend = backend or IndicatorBackend()
        self.atr_period = atr_period
        self.multiplier = multiplier

    @property
    def warmup_period(self) -> int:
        return self.atr_period

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        atr_period = param_int(params, "atr_period", self.atr_period)
        multiplier = param_float(params, "multiplier", self.multiplier)

        if len(bars) < atr_period:
            return empty_series(
                indicator_id=f"SuperTrend_{atr_period}_{multiplier}",
                bars=bars,
                name="SuperTrend",
                warmup_period=atr_period,
                backend_used=self.backend.backend_name,
                parameters={"atr_period": atr_period, "multiplier": multiplier},
            )

        frame = self.to_dataframe(bars)
        high = frame["high"].to_numpy(dtype=float)
        low = frame["low"].to_numpy(dtype=float)
        close = frame["close"].to_numpy(dtype=float)

        atr = self.backend.atr(high, low, close, atr_period)
        hl2 = (high + low) / 2.0
        upper = hl2 + (multiplier * atr)
        lower = hl2 - (multiplier * atr)

        st = np.full((len(bars),), np.nan, dtype=float)
        direction = np.full((len(bars),), "UP", dtype=object)
        signal = np.full((len(bars),), None, dtype=object)

        for idx in range(len(bars)):
            if idx == 0 or not np.isfinite(atr[idx]):
                st[idx] = np.nan
                direction[idx] = "UP"
                continue

            prev_st = st[idx - 1]
            prev_dir = direction[idx - 1]

            if np.isfinite(prev_st):
                if prev_dir == "UP" and lower[idx] < prev_st:
                    lower[idx] = prev_st
                if prev_dir == "DOWN" and upper[idx] > prev_st:
                    upper[idx] = prev_st

            if close[idx] > upper[idx - 1]:
                direction[idx] = "UP"
            elif close[idx] < lower[idx - 1]:
                direction[idx] = "DOWN"
            else:
                direction[idx] = prev_dir

            st[idx] = lower[idx] if direction[idx] == "UP" else upper[idx]
            if direction[idx] != prev_dir:
                signal[idx] = "bullish" if direction[idx] == "UP" else "bearish"

        extras = []
        for idx in range(len(bars)):
            extras.append(
                {
                    "direction": str(direction[idx]),
                    "signal": signal[idx],
                    "atr": float(atr[idx]) if np.isfinite(atr[idx]) else None,
                }
            )

        return build_indicator_series(
            indicator_id=f"SuperTrend_{atr_period}_{multiplier}",
            bars=bars,
            values=st,
            name="SuperTrend",
            warmup_period=atr_period,
            backend_used=self.backend.backend_name,
            parameters={"atr_period": atr_period, "multiplier": multiplier},
            extras=extras,
        )


__all__ = ["SuperTrend"]
