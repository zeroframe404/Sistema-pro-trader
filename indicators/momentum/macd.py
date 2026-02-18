"""MACD indicator."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class MACD(BaseIndicator):
    """MACD line, signal line, and histogram."""

    indicator_id = "MACD"

    def __init__(
        self,
        backend: IndicatorBackend | None = None,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> None:
        self.backend = backend or IndicatorBackend()
        self.fast = fast
        self.slow = slow
        self.signal = signal

    @property
    def warmup_period(self) -> int:
        return self.slow + self.signal

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        fast = int(params.get("fast", self.fast))
        slow = int(params.get("slow", self.slow))
        signal = int(params.get("signal", self.signal))

        warmup = slow + signal
        if len(bars) < warmup:
            return empty_series(
                indicator_id=f"MACD_{fast}_{slow}_{signal}",
                bars=bars,
                name="MACD",
                warmup_period=warmup,
                backend_used=self.backend.backend_name,
                parameters={"fast": fast, "slow": slow, "signal": signal},
            )

        frame = self.to_dataframe(bars)
        close = frame["close"].to_numpy(dtype=float)
        macd_line, signal_line, hist = self.backend.macd(close, fast=fast, slow=slow, signal=signal)

        extras = []
        for idx in range(len(bars)):
            cross: str | None = None
            if idx > 0 and np.isfinite(macd_line[idx]) and np.isfinite(signal_line[idx]):
                if macd_line[idx - 1] <= signal_line[idx - 1] and macd_line[idx] > signal_line[idx]:
                    cross = "bullish"
                elif macd_line[idx - 1] >= signal_line[idx - 1] and macd_line[idx] < signal_line[idx]:
                    cross = "bearish"

            extras.append(
                {
                    "macd": float(macd_line[idx]) if np.isfinite(macd_line[idx]) else None,
                    "signal": float(signal_line[idx]) if np.isfinite(signal_line[idx]) else None,
                    "histogram": float(hist[idx]) if np.isfinite(hist[idx]) else None,
                    "cross": cross,
                }
            )

        return build_indicator_series(
            indicator_id=f"MACD_{fast}_{slow}_{signal}",
            bars=bars,
            values=macd_line,
            name="MACD",
            warmup_period=warmup,
            backend_used=self.backend.backend_name,
            parameters={"fast": fast, "slow": slow, "signal": signal},
            extras=extras,
        )


__all__ = ["MACD"]
