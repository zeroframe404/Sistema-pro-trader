"""Base class contract for all trading strategies."""

from __future__ import annotations

import hashlib
import inspect
import json
from abc import ABC, abstractmethod
from typing import ClassVar

from core.config_models import StrategyConfig
from core.event_bus import EventBus
from core.events import BarCloseEvent, OrderFillEvent, RegimeChangeEvent, SignalEvent, TickEvent


class BaseStrategy(ABC):
    """Abstract strategy interface implemented by all strategy plugins."""

    strategy_id: ClassVar[str] = "base_strategy"
    version: ClassVar[str] = "1.0.0"
    supported_assets: ClassVar[list[str]] = []
    supported_timeframes: ClassVar[list[str]] = []

    def __init__(self, config: StrategyConfig, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus
        self._running = False

    @abstractmethod
    async def on_tick(self, event: TickEvent) -> SignalEvent | None:
        """Handle tick events and optionally return a trading signal."""

    @abstractmethod
    async def on_bar_close(self, event: BarCloseEvent) -> SignalEvent | None:
        """Handle bar close events and optionally return a trading signal."""

    async def on_regime_change(self, event: RegimeChangeEvent) -> None:
        """Optional hook for market regime transitions."""
        _ = event
        return None

    async def on_order_fill(self, event: OrderFillEvent) -> None:
        """Optional hook for broker fill notifications."""
        _ = event
        return None

    def get_version_hash(self) -> str:
        """Compute a reproducible SHA256 hash for strategy code and active parameters."""

        source = inspect.getsource(self.__class__)
        dataset_id = self.config.parameters.get("dataset_id", "default")
        payload = {
            "source": source,
            "params": self.config.parameters,
            "dataset_id": dataset_id,
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def start(self) -> None:
        """Mark strategy lifecycle as running."""

        self._running = True

    async def stop(self) -> None:
        """Mark strategy lifecycle as stopped."""

        self._running = False
