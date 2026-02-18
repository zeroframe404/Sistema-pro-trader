"""Williams %R indicator."""

from __future__ import annotations

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class WilliamsR(BaseIndicator):
    """Williams %R oscillator."""

    indicator_id = "WilliamsR"

    def __init__(self, backend: IndicatorBackend | None = None, period: int = 14) -> None:
        self.backend = backend or IndicatorBackend()
        self.period = period

    @property
    def warmup_period(self) -> int:
        return self.period

    def compute(self, bars: list[OHLCVBar], **params: object) -> IndicatorSeries:
        period = int(params.get("period", self.period))
        if len(bars) < period:
            return empty_series(
                indicator_id=f"WilliamsR_{period}",
                bars=bars,
                name="WilliamsR",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period},
            )

        frame = self.to_dataframe(bars)
        highest = frame["high"].rolling(period, min_periods=period).max()
        lowest = frame["low"].rolling(period, min_periods=period).min()
        williams_r = -100.0 * (highest - frame["close"]) / (highest - lowest)

        return build_indicator_series(
            indicator_id=f"WilliamsR_{period}",
            bars=bars,
            values=williams_r.to_numpy(dtype=float),
            name="WilliamsR",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period},
        )


__all__ = ["WilliamsR"]
