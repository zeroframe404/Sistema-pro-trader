"""Support/resistance detection using pivots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series, param_int
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class SRLevel(BaseModel):
    """One support/resistance level."""

    price: float
    strength: int = Field(ge=1, le=10)
    type: Literal["support", "resistance"]
    touch_count: int = Field(ge=1)
    last_touch: datetime

    @field_validator("last_touch")
    @classmethod
    def ensure_last_touch_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("last_touch must be timezone-aware")
        return value.astimezone(UTC)


class SupportResistanceDetector:
    """Detect levels from fractals or simple pivots."""

    def detect_levels(
        self,
        bars: list[OHLCVBar],
        method: str = "fractal",
        min_touches: int = 2,
        lookback: int = 100,
    ) -> list[SRLevel]:
        if len(bars) < 5:
            return []

        data = bars[-lookback:]
        pivots: list[tuple[float, str, datetime]] = []

        for idx in range(2, len(data) - 2):
            center = data[idx]
            left = data[idx - 2 : idx]
            right = data[idx + 1 : idx + 3]
            neighbor_highs = [item.high for item in left + right]
            neighbor_lows = [item.low for item in left + right]

            if center.high >= max(neighbor_highs) and center.high > min(neighbor_highs):
                pivots.append((center.high, "resistance", center.timestamp_close))
            if center.low <= min(neighbor_lows) and center.low < max(neighbor_lows):
                pivots.append((center.low, "support", center.timestamp_close))

        if method.lower() == "pivot":
            last = data[-1]
            pivot = (last.high + last.low + last.close) / 3.0
            pivots.extend(
                [
                    (pivot, "support", last.timestamp_close),
                    (pivot, "resistance", last.timestamp_close),
                ]
            )

        if min_touches <= 1:
            levels: list[SRLevel] = []
            for price, level_type, touched_at in pivots:
                sr_type: Literal["support", "resistance"]
                if level_type == "resistance":
                    sr_type = "resistance"
                else:
                    sr_type = "support"
                levels.append(
                    SRLevel(
                        price=price,
                        strength=1,
                        type=sr_type,
                        touch_count=1,
                        last_touch=touched_at,
                    )
                )
            return levels

        return self._cluster_levels(pivots, min_touches=min_touches)

    def get_nearest_level(
        self,
        bars: list[OHLCVBar],
        price: float,
        direction: str | None = None,
    ) -> SRLevel | None:
        levels = self.detect_levels(bars, min_touches=1)
        if not levels:
            return None

        candidates = levels
        if direction == "up":
            candidates = [lvl for lvl in levels if lvl.price >= price]
        elif direction == "down":
            candidates = [lvl for lvl in levels if lvl.price <= price]

        if not candidates:
            return None
        return min(candidates, key=lambda item: abs(item.price - price))

    def _cluster_levels(
        self,
        pivots: list[tuple[float, str, datetime]],
        min_touches: int,
    ) -> list[SRLevel]:
        if not pivots:
            return []

        pivots = sorted(pivots, key=lambda item: item[0])
        clusters: list[list[tuple[float, str, datetime]]] = []
        tolerance = 0.002

        for price, pivot_type, touched_at in pivots:
            if not clusters:
                clusters.append([(price, pivot_type, touched_at)])
                continue

            avg_price = sum(item[0] for item in clusters[-1]) / len(clusters[-1])
            if abs(price - avg_price) / max(avg_price, 1e-9) <= tolerance:
                clusters[-1].append((price, pivot_type, touched_at))
            else:
                clusters.append([(price, pivot_type, touched_at)])

        levels: list[SRLevel] = []
        for cluster in clusters:
            touch_count = len(cluster)
            if touch_count < min_touches:
                continue

            avg_price = sum(item[0] for item in cluster) / touch_count
            supports = sum(1 for item in cluster if item[1] == "support")
            resistances = sum(1 for item in cluster if item[1] == "resistance")
            sr_type: Literal["support", "resistance"]
            if supports >= resistances:
                sr_type = "support"
            else:
                sr_type = "resistance"
            strength = max(1, min(10, touch_count))
            last_touch = max(item[2] for item in cluster)
            levels.append(
                SRLevel(
                    price=avg_price,
                    strength=strength,
                    type=sr_type,
                    touch_count=touch_count,
                    last_touch=last_touch,
                )
            )

        return levels


class SupportResistance(BaseIndicator):
    """Indicator wrapper exposing detected nearest level as numeric output."""

    indicator_id = "SupportResistance"

    def __init__(self, backend: IndicatorBackend | None = None) -> None:
        self.backend = backend or IndicatorBackend()
        self.detector = SupportResistanceDetector()

    @property
    def warmup_period(self) -> int:
        return 5

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        method = str(params.get("method", "fractal"))
        min_touches = param_int(params, "min_touches", 2)
        lookback = param_int(params, "lookback", 100)

        if len(bars) < self.warmup_period:
            return empty_series(
                indicator_id="SupportResistance",
                bars=bars,
                name="SupportResistance",
                warmup_period=self.warmup_period,
                backend_used="custom",
                parameters={"method": method, "min_touches": min_touches, "lookback": lookback},
            )

        levels = self.detector.detect_levels(
            bars=bars,
            method=method,
            min_touches=min_touches,
            lookback=lookback,
        )

        import numpy as np

        values = []
        extras = []
        for bar in bars:
            nearest = self.detector.get_nearest_level(bars, price=bar.close)
            values.append(nearest.price if nearest is not None else np.nan)
            extras.append(
                {
                    "nearest": nearest.model_dump(mode="python") if nearest is not None else None,
                    "levels": [level.model_dump(mode="python") for level in levels],
                }
            )

        return build_indicator_series(
            indicator_id="SupportResistance",
            bars=bars,
            values=np.asarray(values, dtype=float),
            name="SupportResistance",
            warmup_period=self.warmup_period,
            backend_used="custom",
            parameters={"method": method, "min_touches": min_touches, "lookback": lookback},
            extras=extras,
        )


__all__ = ["SRLevel", "SupportResistanceDetector", "SupportResistance"]
