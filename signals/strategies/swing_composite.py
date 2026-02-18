"""Swing composite strategy for medium horizons."""

from __future__ import annotations

from datetime import datetime

from data.models import OHLCVBar
from regime.regime_models import MarketRegime, TrendRegime
from signals.signal_models import Signal, SignalDirection, SignalReason
from signals.strategies._helpers import build_signal, ema, rsi, trend_slope
from signals.strategies.base import SignalStrategy


class SwingCompositeStrategy(SignalStrategy):
    """Composite trend/momentum/volatility swing strategy."""

    strategy_id = "swing_composite"
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
        if len(bars) < 90:
            return None

        closes = [bar.close for bar in bars]
        ema21 = ema(closes[-120:], 21)
        ema55 = ema(closes[-160:], 55)
        slope = trend_slope(closes, 30)
        rsi_value = rsi(closes, 14)

        direction = SignalDirection.WAIT
        raw_score = 0.0
        confidence = 0.38
        reasons: list[SignalReason] = []

        if ema21 > ema55 and slope > 0 and rsi_value > 48:
            direction = SignalDirection.BUY
            raw_score = 58.0
            confidence = 0.66
        elif ema21 < ema55 and slope < 0 and rsi_value < 52:
            direction = SignalDirection.SELL
            raw_score = -58.0
            confidence = 0.66

        reasons.append(
            SignalReason(
                factor="EMA_swing",
                value=f"{ema21:.5f}/{ema55:.5f}",
                contribution=0.30 if direction == SignalDirection.BUY else -0.30 if direction == SignalDirection.SELL else 0.0,
                weight=0.30,
                description="Relación EMA21/EMA55 para dirección base de swing",
                direction="bullish" if direction == SignalDirection.BUY else "bearish" if direction == SignalDirection.SELL else "neutral",
                source="indicator",
            )
        )
        reasons.append(
            SignalReason(
                factor="slope",
                value=round(slope, 8),
                contribution=0.20 if slope > 0 else -0.20 if slope < 0 else 0.0,
                weight=0.20,
                description="Pendiente de precio de 30 velas",
                direction="bullish" if slope > 0 else "bearish" if slope < 0 else "neutral",
                source="pattern",
            )
        )

        if regime.trend in {TrendRegime.STRONG_UPTREND, TrendRegime.STRONG_DOWNTREND} and direction != SignalDirection.WAIT:
            confidence = min(0.9, confidence + 0.05)

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
            expiry_minutes=360,
        )
