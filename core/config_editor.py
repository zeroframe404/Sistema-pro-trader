"""Programmatic runtime editor for YAML-backed configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.config_loader import load_config, save_config
from core.config_models import RootConfig, StrategyConfig


class ConfigChange(BaseModel):
    """Pending in-memory configuration change."""

    action: str
    path: str
    old_value: Any
    new_value: Any
    timestamp: datetime


class ConfigEditor:
    """Mutable runtime interface to update system configuration safely."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._config: RootConfig = load_config(config_path)
        self._pending_changes: list[ConfigChange] = []

    @property
    def config(self) -> RootConfig:
        """Return current in-memory configuration."""

        return self._config

    def update_strategy_param(self, strategy_id: str, param: str, value: Any) -> None:
        """Update one strategy parameter and track change history."""

        strategy = self._find_strategy(strategy_id)
        old_value = strategy.parameters.get(param)
        strategy.parameters[param] = value
        self._record_change(
            action="update_strategy_param",
            path=f"strategies.{strategy_id}.parameters.{param}",
            old_value=old_value,
            new_value=value,
        )

    def set_broker_enabled(self, broker_id: str, enabled: bool) -> None:
        """Enable or disable a broker entry by id."""

        for broker in self._config.brokers:
            if broker.broker_id == broker_id:
                old_value = broker.enabled
                broker.enabled = enabled
                self._record_change(
                    action="set_broker_enabled",
                    path=f"brokers.{broker_id}.enabled",
                    old_value=old_value,
                    new_value=enabled,
                )
                return

        raise KeyError(f"Broker not found: {broker_id}")

    def add_strategy(self, strategy: StrategyConfig) -> None:
        """Append a strategy if it does not already exist."""

        if any(item.strategy_id == strategy.strategy_id for item in self._config.strategies):
            raise ValueError(f"Strategy already exists: {strategy.strategy_id}")

        self._config.strategies.append(strategy)
        self._record_change(
            action="add_strategy",
            path=f"strategies.{strategy.strategy_id}",
            old_value=None,
            new_value=strategy.model_dump(mode="python"),
        )

    def save(self) -> None:
        """Persist in-memory changes to disk and clear pending changes."""

        save_config(self._config, self._config_path)
        self._pending_changes.clear()

    def get_pending_changes(self) -> list[ConfigChange]:
        """Return pending changes not yet persisted."""

        return list(self._pending_changes)

    def _find_strategy(self, strategy_id: str) -> StrategyConfig:
        for strategy in self._config.strategies:
            if strategy.strategy_id == strategy_id:
                return strategy
        raise KeyError(f"Strategy not found: {strategy_id}")

    def _record_change(self, action: str, path: str, old_value: Any, new_value: Any) -> None:
        self._pending_changes.append(
            ConfigChange(
                action=action,
                path=path,
                old_value=old_value,
                new_value=new_value,
                timestamp=datetime.now(UTC),
            )
        )
