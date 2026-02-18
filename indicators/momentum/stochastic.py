"""Stochastic and Stoch RSI indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_int
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries
from indicators.momentum.rsi import RSI


class Stochastic(BaseIndicator):
    """Stochastic oscillator (%K and %D)."""

    indicator_id = "Stochastic"

    def __init__(
        self,
        backend: IndicatorBackend | None = None,
        k_period: int = 14,
        d_period: int = 3,
    ) -> None:
        self.backend = backend or IndicatorBackend()
        self.k_period = k_period
        self.d_period = d_period

    @property
    def warmup_period(self) -> int:
        return self.k_period + self.d_period - 1

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        k_period = param_int(params, "k_period", self.k_period)
        d_period = param_int(params, "d_period", self.d_period)
        warmup = k_period + d_period - 1

        if len(bars) < warmup:
            return empty_series(
                indicator_id=f"Stochastic_{k_period}_{d_period}",
                bars=bars,
                name="Stochastic",
                warmup_period=warmup,
                backend_used=self.backend.backend_name,
                parameters={"k_period": k_period, "d_period": d_period},
            )

        frame = self.to_dataframe(bars)
        high = frame["high"].to_numpy(dtype=float)
        low = frame["low"].to_numpy(dtype=float)
        close = frame["close"].to_numpy(dtype=float)
        k, d = self.backend.stoch(high, low, close, k_period=k_period, d_period=d_period)

        extras = []
        for idx in range(len(bars)):
            extras.append(
                {
                    "k": float(k[idx]) if np.isfinite(k[idx]) else None,
                    "d": float(d[idx]) if np.isfinite(d[idx]) else None,
                }
            )

        return build_indicator_series(
            indicator_id=f"Stochastic_{k_period}_{d_period}",
            bars=bars,
            values=k,
            name="Stochastic",
            warmup_period=warmup,
            backend_used=self.backend.backend_name,
            parameters={"k_period": k_period, "d_period": d_period},
            extras=extras,
        )


class StochRSI(BaseIndicator):
    """Stochastic of RSI values."""

    indicator_id = "StochRSI"

    def __init__(
        self,
        backend: IndicatorBackend | None = None,
        rsi_period: int = 14,
        stoch_period: int = 14,
        d_period: int = 3,
    ) -> None:
        self.backend = backend or IndicatorBackend()
        self.rsi_period = rsi_period
        self.stoch_period = stoch_period
        self.d_period = d_period

    @property
    def warmup_period(self) -> int:
        return self.rsi_period + self.stoch_period

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        rsi_period = param_int(params, "rsi_period", self.rsi_period)
        stoch_period = param_int(params, "stoch_period", self.stoch_period)
        d_period = param_int(params, "d_period", self.d_period)

        warmup = rsi_period + stoch_period
        if len(bars) < warmup:
            return empty_series(
                indicator_id=f"StochRSI_{rsi_period}_{stoch_period}_{d_period}",
                bars=bars,
                name="StochRSI",
                warmup_period=warmup,
                backend_used=self.backend.backend_name,
                parameters={
                    "rsi_period": rsi_period,
                    "stoch_period": stoch_period,
                    "d_period": d_period,
                },
            )

        rsi = RSI(backend=self.backend, period=rsi_period).compute(bars)
        rsi_series = pd.Series([item.value for item in rsi.values], dtype=float)
        min_rsi = rsi_series.rolling(stoch_period).min()
        max_rsi = rsi_series.rolling(stoch_period).max()
        stoch = 100.0 * (rsi_series - min_rsi) / (max_rsi - min_rsi)
        signal = stoch.rolling(d_period).mean()

        extras = []
        for idx in range(len(bars)):
            extras.append(
                {
                    "stoch_rsi": float(stoch.iloc[idx]) if np.isfinite(stoch.iloc[idx]) else None,
                    "signal": float(signal.iloc[idx]) if np.isfinite(signal.iloc[idx]) else None,
                }
            )

        return build_indicator_series(
            indicator_id=f"StochRSI_{rsi_period}_{stoch_period}_{d_period}",
            bars=bars,
            values=stoch.to_numpy(dtype=float),
            name="StochRSI",
            warmup_period=warmup,
            backend_used=self.backend.backend_name,
            parameters={
                "rsi_period": rsi_period,
                "stoch_period": stoch_period,
                "d_period": d_period,
            },
            extras=extras,
        )


__all__ = ["Stochastic", "StochRSI"]
