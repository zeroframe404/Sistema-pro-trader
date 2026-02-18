"""Range scalping strategy for ranging regimes."""

from __future__ import annotations

from datetime import datetime

from data.models import OHLCVBar
from regime.regime_models import MarketRegime, TrendRegime
from signals.signal_models import Signal, SignalDirection, SignalReason
from signals.strategies._helpers import build_signal
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


class RangeScalpStrategy(SignalStrategy):
    """Operate mean-reversion entries at range boundaries."""

    strategy_id = "range_scalp"
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
        lookback = _as_int(self.config.params.get("range_lookback", 40), 40)
        if len(bars) < lookback:
            return None

        closes = [bar.close for bar in bars]
        recent = closes[-lookback:]
        support = min(recent)
        resistance = max(recent)
        current = recent[-1]
        width = resistance - support
        if width <= 0:
            return None

        pos = (current - support) / width
        direction = SignalDirection.WAIT
        confidence = 0.34
        raw_score = 0.0
        reasons: list[SignalReason] = []

        if pos <= 0.15:
            direction = SignalDirection.BUY
            confidence = 0.64
            raw_score = 48.0
        elif pos >= 0.85:
            direction = SignalDirection.SELL
            confidence = 0.64
            raw_score = -48.0

        if regime.trend != TrendRegime.RANGING and direction != SignalDirection.WAIT:
            confidence *= 0.70

        reasons.append(
            SignalReason(
                factor="range_position",
                value=round(pos, 3),
                contribution=0.30 if direction == SignalDirection.BUY else -0.30 if direction == SignalDirection.SELL else 0.0,
                weight=0.30,
                description="Posicion relativa dentro del rango reciente",
                direction="bullish" if direction == SignalDirection.BUY else "bearish" if direction == SignalDirection.SELL else "neutral",
                source="pattern",
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
            price=current,
            timestamp=timestamp,
            expiry_minutes=45,
        )
