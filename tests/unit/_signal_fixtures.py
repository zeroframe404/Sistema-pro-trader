from __future__ import annotations

from datetime import UTC, datetime, timedelta

from data.asset_types import AssetClass
from regime.regime_models import LiquidityRegime, MarketRegime, TrendRegime, VolatilityRegime
from signals.signal_models import Signal, SignalDirection, SignalReason, SignalStrength


def make_regime(
    *,
    trend: TrendRegime = TrendRegime.RANGING,
    volatility: VolatilityRegime = VolatilityRegime.MEDIUM,
    liquidity: LiquidityRegime = LiquidityRegime.LIQUID,
    tradeable: bool = True,
) -> MarketRegime:
    return MarketRegime(
        symbol="EURUSD",
        timeframe="H1",
        timestamp=datetime.now(UTC),
        trend=trend,
        volatility=volatility,
        liquidity=liquidity,
        is_tradeable=tradeable,
        no_trade_reasons=[] if tradeable else ["blocked"],
        confidence=0.7,
        recommended_strategies=["trend_following", "momentum_breakout"],
        description="fixture_regime",
        metrics={},
    )


def make_signal(
    *,
    direction: SignalDirection = SignalDirection.BUY,
    confidence: float = 0.7,
    strategy_id: str = "trend_following",
    symbol: str = "EURUSD",
) -> Signal:
    now = datetime.now(UTC)
    return Signal(
        strategy_id=strategy_id,
        strategy_version="1.0.0",
        symbol=symbol,
        broker="mock",
        timeframe="H1",
        timestamp=now,
        run_id="run-test",
        direction=direction,
        strength=SignalStrength.MODERATE,
        raw_score=40.0 if direction == SignalDirection.BUY else -40.0 if direction == SignalDirection.SELL else 0.0,
        confidence=confidence,
        reasons=[
            SignalReason(
                factor="fixture",
                value=1.0,
                contribution=0.5 if direction == SignalDirection.BUY else -0.5 if direction == SignalDirection.SELL else 0.0,
                weight=0.5,
                description="fixture reason",
                direction="bullish" if direction == SignalDirection.BUY else "bearish" if direction == SignalDirection.SELL else "neutral",
                source="indicator",
            )
        ],
        regime=make_regime(),
        horizon="2h",
        entry_price=1.1,
        expires_at=now + timedelta(hours=2),
        metadata={"asset_class": AssetClass.FOREX.value},
    )
