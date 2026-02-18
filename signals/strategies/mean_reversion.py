"""Mean-reversion strategy: RSI extremes + Bollinger location + stoch turn."""

from __future__ import annotations

from datetime import datetime

from data.models import OHLCVBar
from regime.regime_models import MarketRegime, TrendRegime
from signals.signal_models import Signal, SignalDirection, SignalReason
from signals.strategies._helpers import bollinger_percent_b, build_signal, rsi, stochastic_k
from signals.strategies.base import SignalStrategy


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


class MeanReversionStrategy(SignalStrategy):
    """Oversold/overbought reversal strategy."""

    strategy_id = "mean_reversion"
    version = "1.0.0"

    async def generate(
        self,
        *,
        symbol: str,
        broker: str,
        timeframe: str,
        horizon: str,
        bars: list[OHLCVBar],
        regime: MarketRegime,
        timestamp: datetime,
    ) -> Signal | None:
        if len(bars) < 30:
            return None

        closes = [bar.close for bar in bars]
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]

        rsi_value = rsi(closes, _as_int(self.config.params.get("rsi_period", 14), 14))
        percent_b = bollinger_percent_b(closes, 20, 2.0)
        stoch_k = stochastic_k(highs, lows, closes, 14)

        rsi_low = _as_float(self.config.params.get("rsi_low", 30), 30.0)
        rsi_high = _as_float(self.config.params.get("rsi_high", 70), 70.0)

        direction = SignalDirection.WAIT
        raw_score = 0.0
        confidence = 0.35
        reasons: list[SignalReason] = []

        if rsi_value <= rsi_low and percent_b <= 0.10 and stoch_k <= 25:
            direction = SignalDirection.BUY
            raw_score = 60.0
            confidence = 0.68
            reasons.append(
                SignalReason(
                    factor="RSI",
                    value=rsi_value,
                    contribution=0.35,
                    weight=0.35,
                    description="RSI en sobreventa",
                    direction="bullish",
                    source="indicator",
                )
            )
        elif rsi_value >= rsi_high and percent_b >= 0.90 and stoch_k >= 75:
            direction = SignalDirection.SELL
            raw_score = -60.0
            confidence = 0.68
            reasons.append(
                SignalReason(
                    factor="RSI",
                    value=rsi_value,
                    contribution=-0.35,
                    weight=0.35,
                    description="RSI en sobrecompra",
                    direction="bearish",
                    source="indicator",
                )
            )

        reasons.append(
            SignalReason(
                factor="%B",
                value=round(percent_b, 4),
                contribution=0.15 if direction == SignalDirection.BUY else -0.15 if direction == SignalDirection.SELL else 0.0,
                weight=0.20,
                description="Posicion relativa dentro de bandas de Bollinger",
                direction="bullish" if direction == SignalDirection.BUY else "bearish" if direction == SignalDirection.SELL else "neutral",
                source="indicator",
            )
        )

        if regime.trend in {TrendRegime.STRONG_UPTREND, TrendRegime.STRONG_DOWNTREND} and direction != SignalDirection.WAIT:
            confidence *= 0.75
            reasons.append(
                SignalReason(
                    factor="regime",
                    value=regime.trend.value,
                    contribution=-0.20,
                    weight=0.20,
                    description="Reversion contra tendencia fuerte reduce probabilidad",
                    direction="neutral",
                    source="regime",
                )
            )

        return build_signal(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            symbol=symbol,
            broker=broker,
            timeframe=timeframe,
            run_id=self.run_id,
            direction=direction,
            raw_score=raw_score,
            confidence=confidence,
            reasons=reasons,
            regime=regime,
            horizon=horizon,
            price=closes[-1],
            timestamp=timestamp,
        )
