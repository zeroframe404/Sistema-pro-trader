"""Adapter to expose Module 3 signal strategies as BaseStrategy plugins."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC

from core.base_strategy import BaseStrategy
from core.config_models import SignalStrategyConfig, StrategyConfig
from core.event_bus import EventBus
from core.events import BarCloseEvent, SignalEvent, TickEvent
from data.asset_types import AssetClass
from data.models import OHLCVBar
from regime.regime_models import LiquidityRegime, MarketRegime, TrendRegime, VolatilityRegime
from signals.strategies.base import SignalStrategy
from signals.strategies.investment_fundamental import InvestmentFundamentalStrategy
from signals.strategies.mean_reversion import MeanReversionStrategy
from signals.strategies.momentum_breakout import MomentumBreakoutStrategy
from signals.strategies.range_scalp import RangeScalpStrategy
from signals.strategies.scalping_reversal import ScalpingReversalStrategy
from signals.strategies.swing_composite import SwingCompositeStrategy
from signals.strategies.trend_following import TrendFollowingStrategy


class SignalStrategyAdapter(BaseStrategy):
    """Bridge internal SignalStrategy to BaseStrategy interface."""

    strategy_id = "signal_strategy_adapter"
    version = "1.0.0"

    STRATEGY_MAP: dict[str, type[SignalStrategy]] = {
        "trend_following": TrendFollowingStrategy,
        "mean_reversion": MeanReversionStrategy,
        "momentum_breakout": MomentumBreakoutStrategy,
        "scalping_reversal": ScalpingReversalStrategy,
        "swing_composite": SwingCompositeStrategy,
        "investment_fundamental": InvestmentFundamentalStrategy,
        "range_scalp": RangeScalpStrategy,
    }

    def __init__(
        self,
        config: StrategyConfig,
        event_bus: EventBus,
        wrapped_strategy: SignalStrategy | None = None,
    ) -> None:
        super().__init__(config=config, event_bus=event_bus)
        self._wrapped = wrapped_strategy or self._build_wrapped(config)
        self._bars: dict[str, deque[OHLCVBar]] = defaultdict(lambda: deque(maxlen=500))

    @classmethod
    def from_config(cls, config: StrategyConfig, event_bus: EventBus) -> SignalStrategyAdapter:
        """Factory used by plugin manager when adapter is loaded dynamically."""

        return cls(config=config, event_bus=event_bus, wrapped_strategy=None)

    async def on_tick(self, event: TickEvent) -> SignalEvent | None:
        _ = event
        return None

    async def on_bar_close(self, event: BarCloseEvent) -> SignalEvent | None:
        key = f"{event.symbol}|{event.timeframe}"
        self._bars[key].append(
            OHLCVBar(
                symbol=event.symbol,
                broker=event.broker,
                timeframe=event.timeframe,
                timestamp_open=event.timestamp_open.astimezone(UTC),
                timestamp_close=event.timestamp_close.astimezone(UTC),
                open=event.open,
                high=event.high,
                low=event.low,
                close=event.close,
                volume=event.volume,
                source="signal_adapter",
                asset_class=AssetClass.UNKNOWN,
            )
        )

        bars = list(self._bars[key])
        regime = MarketRegime(
            symbol=event.symbol,
            timeframe=event.timeframe,
            timestamp=event.timestamp_close.astimezone(UTC),
            trend=TrendRegime.RANGING,
            volatility=VolatilityRegime.MEDIUM,
            liquidity=LiquidityRegime.LIQUID,
            is_tradeable=True,
            no_trade_reasons=[],
            confidence=0.5,
            recommended_strategies=[],
            description="adapter_default_regime",
        )

        signal = await self._wrapped.generate(
            symbol=event.symbol,
            broker=event.broker,
            timeframe=event.timeframe,
            horizon="1h",
            bars=bars,
            regime=regime,
            timestamp=event.timestamp_close,
        )
        if signal is None:
            return None

        return SignalEvent(
            source=f"signals.adapter.{self._wrapped.strategy_id}",
            run_id=signal.run_id,
            symbol=signal.symbol,
            broker=signal.broker,
            strategy_id=signal.strategy_id,
            strategy_version=signal.strategy_version,
            direction=signal.direction.value,
            confidence=signal.confidence,
            reasons=[reason.model_dump(mode="python") for reason in signal.reasons],
            timeframe=signal.timeframe,
            horizon=signal.horizon,
            timestamp=signal.timestamp,
        )

    def _build_wrapped(self, config: StrategyConfig) -> SignalStrategy:
        wrapped_id = str(config.parameters.get("wrapped_strategy", "trend_following"))
        strategy_cls = self.STRATEGY_MAP.get(wrapped_id)
        if strategy_cls is None:
            raise KeyError(f"Unsupported wrapped_strategy: {wrapped_id}")
        strategy_config = SignalStrategyConfig(strategy_id=wrapped_id, params={})
        return strategy_cls(config=strategy_config, run_id="adapter")
