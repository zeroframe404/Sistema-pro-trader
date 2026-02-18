"""RSI indicator and helpers."""

from __future__ import annotations

from data.models import OHLCVBar
from indicators._utils import build_indicator_series, empty_series
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries


class RSI(BaseIndicator):
    """Wilder RSI indicator."""

    indicator_id = "RSI"

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
                indicator_id=f"RSI_{period}",
                bars=bars,
                name="RSI",
                warmup_period=period,
                backend_used=self.backend.backend_name,
                parameters={"period": period},
            )

        frame = self.to_dataframe(bars)
        close = frame["close"].to_numpy(dtype=float)
        values = self.backend.rsi(close, period)
        return build_indicator_series(
            indicator_id=f"RSI_{period}",
            bars=bars,
            values=values,
            name="RSI",
            warmup_period=period,
            backend_used=self.backend.backend_name,
            parameters={"period": period},
        )

    @staticmethod
    def is_overbought(value: float, threshold: float = 70.0) -> bool:
        return value >= threshold

    @staticmethod
    def is_oversold(value: float, threshold: float = 30.0) -> bool:
        return value <= threshold

    def detect_divergence(
        self,
        bars: list[OHLCVBar],
        price_bars: list[OHLCVBar] | None = None,
    ) -> str | None:
        if len(bars) < (self.period + 5):
            return None

        rsi_series = self.compute(bars)
        rsi_vals = [item.value for item in rsi_series.values if item.value is not None]
        if len(rsi_vals) < 5:
            return None

        prices_source = price_bars if price_bars is not None else bars
        closes = [item.close for item in prices_source][-len(rsi_vals) :]
        rsi_recent = rsi_vals[-5:]
        close_recent = closes[-5:]

        price_trend = close_recent[-1] - close_recent[0]
        rsi_trend = rsi_recent[-1] - rsi_recent[0]

        if price_trend < 0 and rsi_trend > 0:
            return "bullish"
        if price_trend > 0 and rsi_trend < 0:
            return "bearish"
        return None


__all__ = ["RSI"]
