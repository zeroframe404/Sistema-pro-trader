"""Base contract for built-in signal strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from core.config_models import SignalStrategyConfig
from data.models import OHLCVBar
from regime.regime_models import MarketRegime
from signals.signal_models import Signal


class SignalStrategy(ABC):
    """Internal deterministic strategy contract for SignalEngine."""

    strategy_id: str = "signal_strategy"
    version: str = "1.0.0"

    def __init__(self, config: SignalStrategyConfig, run_id: str) -> None:
        self.config = config
        self.run_id = run_id

    @abstractmethod
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
        """Return one signal candidate or None."""
