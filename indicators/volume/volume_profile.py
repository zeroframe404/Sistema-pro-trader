"""Simplified volume profile indicator."""

from __future__ import annotations

import numpy as np

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class VolumeProfile(BaseIndicator):
    """Price-bin volume distribution with POC estimate."""

    indicator_id = "VolumeProfile"

    def __init__(self, backend: IndicatorBackend | None = None, bins: int = 20) -> None:
        self.backend = backend or IndicatorBackend()
        self.bins = bins

    @property
    def warmup_period(self) -> int:
        return 10

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        bins = int(params.get("bins", self.bins))
        if len(bars) < self.warmup_period:
            return empty_series(
                indicator_id=f"VolumeProfile_{bins}",
                bars=bars,
                name="VolumeProfile",
                warmup_period=self.warmup_period,
                backend_used=self.backend.backend_name,
                parameters={"bins": bins},
            )

        prices = np.asarray([bar.close for bar in bars], dtype=float)
        volumes = np.asarray([bar.volume for bar in bars], dtype=float)
        hist, edges = np.histogram(prices, bins=bins, weights=volumes)
        max_idx = int(np.argmax(hist)) if hist.size else 0
        poc = float((edges[max_idx] + edges[max_idx + 1]) / 2.0) if edges.size >= 2 else None

        extras = []
        for _bar in bars:
            extras.append(
                {
                    "poc": poc,
                    "bins": bins,
                    "histogram": hist.tolist(),
                }
            )

        values = np.full((len(bars),), np.nan if poc is None else poc, dtype=float)
        return build_indicator_series(
            indicator_id=f"VolumeProfile_{bins}",
            bars=bars,
            values=values,
            name="VolumeProfile",
            warmup_period=self.warmup_period,
            backend_used=self.backend.backend_name,
            parameters={"bins": bins},
            extras=extras,
        )


__all__ = ["VolumeProfile"]
