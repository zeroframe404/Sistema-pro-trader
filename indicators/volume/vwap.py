"""VWAP indicator with UTC daily reset."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class VWAP(BaseIndicator):
    """Intraday VWAP and standard deviation bands."""

    indicator_id = "VWAP"

    def __init__(self, backend: IndicatorBackend | None = None) -> None:
        self.backend = backend or IndicatorBackend()

    @property
    def warmup_period(self) -> int:
        return 1

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        _ = params
        if not bars:
            return empty_series(
                indicator_id="VWAP",
                bars=bars,
                name="VWAP",
                warmup_period=1,
                backend_used=self.backend.backend_name,
                parameters={},
            )

        frame = self.to_dataframe(bars)
        frame["day"] = frame["timestamp_open"].dt.floor("D")
        typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3.0
        volume = frame["volume"].fillna(0.0)

        if float(volume.sum()) <= 0:
            return empty_series(
                indicator_id="VWAP",
                bars=bars,
                name="VWAP",
                warmup_period=1,
                backend_used=self.backend.backend_name,
                parameters={},
            )

        cum_pv = (typical_price * volume).groupby(frame["day"]).cumsum()
        cum_vol = volume.groupby(frame["day"]).cumsum()
        vwap = cum_pv / cum_vol.replace(0, np.nan)

        extras = []
        for day, group in frame.groupby("day", sort=False):
            day_idx = list(group.index)
            day_tp = typical_price.iloc[day_idx]
            day_vwap = vwap.iloc[day_idx]
            std = (day_tp - day_vwap).expanding().std(ddof=0).fillna(0.0)
            for local_i, _idx in enumerate(day_idx):
                sigma = float(std.iloc[local_i])
                base = float(day_vwap.iloc[local_i]) if np.isfinite(day_vwap.iloc[local_i]) else None
                extras.append(
                    {
                        "vwap": base,
                        "plus_1sigma": (base + sigma) if base is not None else None,
                        "minus_1sigma": (base - sigma) if base is not None else None,
                        "plus_2sigma": (base + 2.0 * sigma) if base is not None else None,
                        "minus_2sigma": (base - 2.0 * sigma) if base is not None else None,
                        "plus_3sigma": (base + 3.0 * sigma) if base is not None else None,
                        "minus_3sigma": (base - 3.0 * sigma) if base is not None else None,
                        "session": str(day),
                    }
                )

        extras_sorted = [extras[idx] for idx in np.argsort(frame.index.to_numpy())]

        return build_indicator_series(
            indicator_id="VWAP",
            bars=bars,
            values=vwap.to_numpy(dtype=float),
            name="VWAP",
            warmup_period=1,
            backend_used=self.backend.backend_name,
            parameters={},
            extras=extras_sorted,
        )


__all__ = ["VWAP"]
