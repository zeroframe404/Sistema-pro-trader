"""Keltner Channel indicator."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_float, param_int
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class KeltnerChannel(BaseIndicator):
    """EMA center line plus ATR envelopes."""

    indicator_id = "KeltnerChannel"

    def __init__(
        self,
        backend: IndicatorBackend | None = None,
        ema_period: int = 20,
        atr_period: int = 10,
        multiplier: float = 2.0,
    ) -> None:
        self.backend = backend or IndicatorBackend()
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.multiplier = multiplier

    @property
    def warmup_period(self) -> int:
        return max(self.ema_period, self.atr_period)

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        ema_period = param_int(params, "ema_period", self.ema_period)
        atr_period = param_int(params, "atr_period", self.atr_period)
        multiplier = param_float(params, "multiplier", self.multiplier)
        warmup = max(ema_period, atr_period)

        if len(bars) < warmup:
            return empty_series(
                indicator_id=f"Keltner_{ema_period}_{atr_period}_{multiplier}",
                bars=bars,
                name="KeltnerChannel",
                warmup_period=warmup,
                backend_used=self.backend.backend_name,
                parameters={
                    "ema_period": ema_period,
                    "atr_period": atr_period,
                    "multiplier": multiplier,
                },
            )

        frame = self.to_dataframe(bars)
        close = frame["close"].to_numpy(dtype=float)
        high = frame["high"].to_numpy(dtype=float)
        low = frame["low"].to_numpy(dtype=float)

        center = self.backend.ema(close, ema_period)
        atr = self.backend.atr(high, low, close, atr_period)
        upper = center + (atr * multiplier)
        lower = center - (atr * multiplier)

        extras = []
        for idx in range(len(bars)):
            extras.append(
                {
                    "upper": float(upper[idx]) if np.isfinite(upper[idx]) else None,
                    "lower": float(lower[idx]) if np.isfinite(lower[idx]) else None,
                    "atr": float(atr[idx]) if np.isfinite(atr[idx]) else None,
                }
            )

        return build_indicator_series(
            indicator_id=f"Keltner_{ema_period}_{atr_period}_{multiplier}",
            bars=bars,
            values=center,
            name="KeltnerChannel",
            warmup_period=warmup,
            backend_used=self.backend.backend_name,
            parameters={
                "ema_period": ema_period,
                "atr_period": atr_period,
                "multiplier": multiplier,
            },
            extras=extras,
        )


__all__ = ["KeltnerChannel"]
