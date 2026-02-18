"""Trend-following strategy: EMA structure + ADX + regime confirmation."""

from __future__ import annotations

from datetime import datetime

from data.models import OHLCVBar
from regime.regime_models import MarketRegime, TrendRegime
from signals.signal_models import Signal, SignalDirection, SignalReason
from signals.strategies._helpers import build_signal, ema, rsi
from signals.strategies.base import SignalStrategy


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


class TrendFollowingStrategy(SignalStrategy):
    """EMA trend continuation strategy."""

    strategy_id = "trend_following"
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
        if len(bars) < 50:
            return None

        closes = [bar.close for bar in bars]
        ema20 = ema(closes[-120:], 20)
        ema50 = ema(closes[-160:], 50)
        ema200 = ema(closes[-260:], 200)
        adx = _as_float(regime.metrics.get("adx", 20.0), 20.0)
        rsi_value = rsi(closes, 14)
        adx_min = _as_float(self.config.params.get("adx_min", 20), 20.0)

        reasons: list[SignalReason] = []
        raw_score = 0.0
        direction = SignalDirection.WAIT
        confidence = 0.35

        if ema20 > ema50 > ema200 and adx >= adx_min:
            direction = SignalDirection.BUY
            raw_score = 65.0
            confidence = 0.72
            reasons.append(
                SignalReason(
                    factor="EMA_cross",
                    value=f"{ema20:.5f}>{ema50:.5f}>{ema200:.5f}",
                    contribution=0.45,
                    weight=0.45,
                    description="EMA20 > EMA50 > EMA200 confirma estructura alcista",
                    direction="bullish",
                    source="indicator",
                )
            )
        elif ema20 < ema50 < ema200 and adx >= adx_min:
            direction = SignalDirection.SELL
            raw_score = -65.0
            confidence = 0.72
            reasons.append(
                SignalReason(
                    factor="EMA_cross",
                    value=f"{ema20:.5f}<{ema50:.5f}<{ema200:.5f}",
                    contribution=-0.45,
                    weight=0.45,
                    description="EMA20 < EMA50 < EMA200 confirma estructura bajista",
                    direction="bearish",
                    source="indicator",
                )
            )

        if adx < adx_min:
            direction = SignalDirection.WAIT
            confidence = 0.30
            raw_score = 0.0
            reasons.append(
                SignalReason(
                    factor="ADX",
                    value=adx,
                    contribution=-0.30,
                    weight=0.30,
                    description="ADX bajo sugiere mercado lateral",
                    direction="neutral",
                    source="regime",
                )
            )

        if regime.trend in {TrendRegime.STRONG_UPTREND, TrendRegime.STRONG_DOWNTREND}:
            confidence = min(1.0, confidence + 0.08)
            reasons.append(
                SignalReason(
                    factor="regime",
                    value=regime.trend.value,
                    contribution=0.15 if direction != SignalDirection.WAIT else 0.0,
                    weight=0.15,
                    description=f"Regimen {regime.trend.value} favorece seguimiento de tendencia",
                    direction="bullish" if direction == SignalDirection.BUY else "bearish" if direction == SignalDirection.SELL else "neutral",
                    source="regime",
                )
            )

        if direction == SignalDirection.BUY and rsi_value >= _as_float(self.config.params.get("overbought_rsi", 75), 75.0):
            confidence *= 0.82
            reasons.append(
                SignalReason(
                    factor="RSI",
                    value=rsi_value,
                    contribution=-0.10,
                    weight=0.10,
                    description="RSI alto reduce calidad de entrada alcista",
                    direction="bearish",
                    source="indicator",
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
