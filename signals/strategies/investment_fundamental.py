"""Long-horizon investment heuristic strategy."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from data.models import OHLCVBar
from regime.regime_models import MarketRegime
from signals.signal_models import Signal, SignalDirection, SignalReason
from signals.strategies._helpers import build_signal, trend_slope
from signals.strategies.base import SignalStrategy


class InvestmentFundamentalStrategy(SignalStrategy):
    """Proxy fundamental strategy using long-term price structure."""

    strategy_id = "investment_fundamental"
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
        if len(bars) < 120:
            return None

        closes = np.asarray([bar.close for bar in bars], dtype=float)
        slope = trend_slope(closes.tolist(), 90)
        returns = np.diff(np.log(closes))
        vol = float(np.std(returns[-90:])) if len(returns) >= 90 else float(np.std(returns))
        max_close = float(np.max(closes[-120:]))
        current = float(closes[-1])
        drawdown = 0.0 if max_close == 0 else (max_close - current) / max_close

        direction = SignalDirection.WAIT
        raw_score = 0.0
        confidence = 0.36
        reasons: list[SignalReason] = []

        if slope > 0 and drawdown < 0.20:
            direction = SignalDirection.BUY
            raw_score = 52.0
            confidence = 0.62
        elif slope < 0 and drawdown > 0.30:
            direction = SignalDirection.SELL
            raw_score = -45.0
            confidence = 0.56

        if vol > 0.04 and direction != SignalDirection.WAIT:
            confidence *= 0.85

        reasons.extend(
            [
                SignalReason(
                    factor="trend_90",
                    value=round(slope, 8),
                    contribution=0.25 if slope > 0 else -0.25 if slope < 0 else 0.0,
                    weight=0.25,
                    description="Pendiente de 90 velas como proxy de fundamento de largo plazo",
                    direction="bullish" if slope > 0 else "bearish" if slope < 0 else "neutral",
                    source="fundamental",
                ),
                SignalReason(
                    factor="drawdown",
                    value=round(drawdown, 4),
                    contribution=-0.12 if drawdown > 0.25 else 0.10,
                    weight=0.15,
                    description="Nivel de retroceso respecto al maximo reciente",
                    direction="bullish" if drawdown < 0.25 else "bearish",
                    source="fundamental",
                ),
            ]
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
            expiry_minutes=1440,
        )
