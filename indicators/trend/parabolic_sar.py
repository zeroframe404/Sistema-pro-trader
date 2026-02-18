"""Parabolic SAR indicator."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_float
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class ParabolicSAR(BaseIndicator):
    """Parabolic stop-and-reverse indicator."""

    indicator_id = "ParabolicSAR"

    def __init__(
        self,
        backend: IndicatorBackend | None = None,
        step: float = 0.02,
        max_step: float = 0.2,
    ) -> None:
        self.backend = backend or IndicatorBackend()
        self.step = step
        self.max_step = max_step

    @property
    def warmup_period(self) -> int:
        return 2

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        step = param_float(params, "step", self.step)
        max_step = param_float(params, "max_step", self.max_step)

        if len(bars) < 2:
            return empty_series(
                indicator_id=f"ParabolicSAR_{step}_{max_step}",
                bars=bars,
                name="ParabolicSAR",
                warmup_period=self.warmup_period,
                backend_used=self.backend.backend_name,
                parameters={"step": step, "max_step": max_step},
            )

        frame = self.to_dataframe(bars)
        high = frame["high"].to_numpy(dtype=float)
        low = frame["low"].to_numpy(dtype=float)

        sar = np.full((len(bars),), np.nan, dtype=float)
        trend_up = True
        af = step
        ep = high[0]
        sar[0] = low[0]

        for idx in range(1, len(bars)):
            prev_sar = sar[idx - 1]
            sar[idx] = prev_sar + af * (ep - prev_sar)

            if trend_up:
                sar[idx] = min(sar[idx], low[idx - 1], low[idx])
                if high[idx] > ep:
                    ep = high[idx]
                    af = min(af + step, max_step)
                if low[idx] < sar[idx]:
                    trend_up = False
                    sar[idx] = ep
                    ep = low[idx]
                    af = step
            else:
                sar[idx] = max(sar[idx], high[idx - 1], high[idx])
                if low[idx] < ep:
                    ep = low[idx]
                    af = min(af + step, max_step)
                if high[idx] > sar[idx]:
                    trend_up = True
                    sar[idx] = ep
                    ep = high[idx]
                    af = step

        return build_indicator_series(
            indicator_id=f"ParabolicSAR_{step}_{max_step}",
            bars=bars,
            values=sar,
            name="ParabolicSAR",
            warmup_period=self.warmup_period,
            backend_used=self.backend.backend_name,
            parameters={"step": step, "max_step": max_step},
        )


__all__ = ["ParabolicSAR"]
