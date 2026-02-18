"""Singleton registry for loaded strategy instances and lifecycle states."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any

from core.base_strategy import BaseStrategy
from core.event_bus import EventBus
from core.events import StrategyStateChangeEvent


class StrategyStatus(StrEnum):
    """Strategy lifecycle states."""

    LOADING = "LOADING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class StrategyRegistry:
    """Singleton registry that stores strategy objects and state transitions."""

    _instance: StrategyRegistry | None = None
    _event_bus: EventBus | None

    def __new__(cls, *args: Any, **kwargs: Any) -> StrategyRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, event_bus: EventBus | None = None, run_id: str = "unknown") -> None:
        if getattr(self, "_initialized", False):
            if event_bus is not None:
                self._event_bus = event_bus
            self._run_id = run_id
            return

        self._event_bus = event_bus
        self._run_id = run_id
        self._strategies: dict[str, BaseStrategy] = {}
        self._states: dict[str, StrategyStatus] = {}
        self._initialized = True

    def register(self, strategy: BaseStrategy) -> None:
        """Register strategy and move state to ACTIVE."""

        strategy_id = strategy.config.strategy_id
        previous = self._states.get(strategy_id)
        self._strategies[strategy_id] = strategy
        self._states[strategy_id] = StrategyStatus.ACTIVE
        self._emit_state_change(strategy_id, previous, StrategyStatus.ACTIVE, None)

    def unregister(self, strategy_id: str) -> None:
        """Unregister strategy and emit STOPPED transition."""

        previous = self._states.get(strategy_id)
        self._strategies.pop(strategy_id, None)
        self._states[strategy_id] = StrategyStatus.STOPPED
        self._emit_state_change(strategy_id, previous, StrategyStatus.STOPPED, "unregistered")

    def set_state(self, strategy_id: str, state: StrategyStatus, reason: str | None = None) -> None:
        """Set strategy state and emit transition event."""

        previous = self._states.get(strategy_id)
        self._states[strategy_id] = state
        self._emit_state_change(strategy_id, previous, state, reason)

    def get(self, strategy_id: str) -> BaseStrategy | None:
        """Get registered strategy by id."""

        return self._strategies.get(strategy_id)

    def list_all(self) -> list[dict[str, str]]:
        """List all strategies with current state."""

        return [
            {"strategy_id": strategy_id, "state": self._states[strategy_id].value}
            for strategy_id in sorted(self._states)
        ]

    def _emit_state_change(
        self,
        strategy_id: str,
        previous: StrategyStatus | None,
        new: StrategyStatus,
        reason: str | None,
    ) -> None:
        if self._event_bus is None:
            return

        event = StrategyStateChangeEvent(
            source="strategy_registry",
            run_id=self._run_id,
            strategy_id=strategy_id,
            previous_state=previous.value if previous else None,
            new_state=new.value,
            reason=reason,
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        loop.create_task(self._event_bus.publish(event))
