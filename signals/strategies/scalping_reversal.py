"""Short-horizon scalping reversal strategy."""

from __future__ import annotations

from datetime import datetime

from data.models import OHLCVBar
from regime.regime_models import MarketRegime
from signals.signal_models import Signal, SignalDirection, SignalReason
from signals.strategies._helpers import build_signal, rsi
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


class ScalpingReversalStrategy(SignalStrategy):
    """Fast reversal strategy for scalp horizons."""

    strategy_id = "scalping_reversal"
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
        if len(bars) < 15:
            return None

        closes = [bar.close for bar in bars]
        fast_rsi = rsi(closes, _as_int(self.config.params.get("fast_rsi_period", 7), 7))
        last = bars[-1]
        candle_body = abs(last.close - last.open)
        upper_wick = last.high - max(last.close, last.open)
        lower_wick = min(last.close, last.open) - last.low

        direction = SignalDirection.WAIT
        confidence = 0.33
        raw_score = 0.0
        reasons: list[SignalReason] = []

        if fast_rsi <= 25 and lower_wick > candle_body * 1.2:
            direction = SignalDirection.BUY
            confidence = 0.63
            raw_score = 52.0
            reasons.append(
                SignalReason(
                    factor="wick_reversal",
                    value=round(lower_wick, 6),
                    contribution=0.35,
                    weight=0.35,
                    description="Vela con mecha inferior dominante y RSI bajo",
                    direction="bullish",
                    source="pattern",
                )
            )
        elif fast_rsi >= 75 and upper_wick > candle_body * 1.2:
            direction = SignalDirection.SELL
            confidence = 0.63
            raw_score = -52.0
            reasons.append(
                SignalReason(
                    factor="wick_reversal",
                    value=round(upper_wick, 6),
                    contribution=-0.35,
                    weight=0.35,
                    description="Vela con mecha superior dominante y RSI alto",
                    direction="bearish",
                    source="pattern",
                )
            )

        reasons.append(
            SignalReason(
                factor="RSI_fast",
                value=round(fast_rsi, 2),
                contribution=0.18 if direction == SignalDirection.BUY else -0.18 if direction == SignalDirection.SELL else 0.0,
                weight=0.25,
                description="Momentum de muy corto plazo",
                direction="bullish" if direction == SignalDirection.BUY else "bearish" if direction == SignalDirection.SELL else "neutral",
                source="momentum",
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
            price=last.close,
            timestamp=timestamp,
            expiry_minutes=30,
        )
