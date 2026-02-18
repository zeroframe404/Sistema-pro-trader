"""Momentum breakout strategy."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from data.models import OHLCVBar
from regime.regime_models import MarketRegime
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


class MomentumBreakoutStrategy(SignalStrategy):
    """Breakout above/below range with volume confirmation."""

    strategy_id = "momentum_breakout"
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
        lookback = _as_int(self.config.params.get("lookback", 20), 20)
        if len(bars) < lookback + 5:
            return None

        closes = [bar.close for bar in bars]
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        volumes = np.asarray([bar.volume for bar in bars], dtype=float)

        resistance = max(highs[-lookback - 1 : -1])
        support = min(lows[-lookback - 1 : -1])
        current = closes[-1]
        avg_volume = float(np.mean(volumes[-lookback - 1 : -1])) if len(volumes) > lookback else float(np.mean(volumes))
        volume_ratio = 0.0 if avg_volume == 0 else float(volumes[-1] / max(avg_volume, 1e-9))

        direction = SignalDirection.WAIT
        raw_score = 0.0
        confidence = 0.35
        reasons: list[SignalReason] = []
        volume_ratio_min = _as_float(self.config.params.get("volume_ratio_min", 1.1), 1.1)

        if current >= (resistance * 0.999) and volume_ratio >= volume_ratio_min:
            direction = SignalDirection.BUY
            raw_score = 62.0
            confidence = min(0.85, 0.55 + (volume_ratio - 1.0) * 0.2)
            reasons.append(
                SignalReason(
                    factor="breakout",
                    value=round(current - resistance, 6),
                    contribution=0.40,
                    weight=0.40,
                    description="Ruptura alcista sobre resistencia con confirmacion de volumen",
                    direction="bullish",
                    source="pattern",
                )
            )
        elif current <= (support * 1.001) and volume_ratio >= volume_ratio_min:
            direction = SignalDirection.SELL
            raw_score = -62.0
            confidence = min(0.85, 0.55 + (volume_ratio - 1.0) * 0.2)
            reasons.append(
                SignalReason(
                    factor="breakout",
                    value=round(support - current, 6),
                    contribution=-0.40,
                    weight=0.40,
                    description="Ruptura bajista bajo soporte con confirmacion de volumen",
                    direction="bearish",
                    source="pattern",
                )
            )

        reasons.append(
            SignalReason(
                factor="volume_ratio",
                value=round(volume_ratio, 3),
                contribution=0.15 if direction == SignalDirection.BUY else -0.15 if direction == SignalDirection.SELL else 0.0,
                weight=0.20,
                description="Relacion de volumen respecto al promedio reciente",
                direction="bullish" if direction == SignalDirection.BUY else "bearish" if direction == SignalDirection.SELL else "neutral",
                source="volume",
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
        )
