"""Dynamic strategy discovery and loading utilities."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.base_strategy import BaseStrategy
from core.config_models import StrategyConfig
from core.event_bus import EventBus


@dataclass(slots=True)
class StrategyMeta:
    """Metadata for discovered or loaded strategy classes."""

    strategy_id: str
    strategy_class: str
    version: str
    version_hash: str
    status: str


_loaded_strategies: dict[str, StrategyMeta] = {}


def discover_strategies(strategies_dir: Path) -> list[StrategyMeta]:
    """Scan strategy modules and return metadata for BaseStrategy subclasses."""

    if not strategies_dir.exists():
        return []

    if str(strategies_dir.parent) not in sys.path:
        sys.path.insert(0, str(strategies_dir.parent))

    results: list[StrategyMeta] = []
    package_name = strategies_dir.name

    for file_path in sorted(strategies_dir.glob("*.py")):
        if file_path.name.startswith("_"):
            continue

        module_name = f"{package_name}.{file_path.stem}"
        importlib.invalidate_caches()
        module = importlib.import_module(module_name)

        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate is BaseStrategy:
                continue
            if not issubclass(candidate, BaseStrategy):
                continue
            if candidate.__module__ != module.__name__:
                continue

            strategy_id = getattr(candidate, "strategy_id", candidate.__name__.lower())
            version = getattr(candidate, "version", "0.0.0")
            version_hash = compute_version_hash(candidate, {}, "default")
            results.append(
                StrategyMeta(
                    strategy_id=strategy_id,
                    strategy_class=f"{module_name}.{candidate.__name__}",
                    version=version,
                    version_hash=version_hash,
                    status="discovered",
                )
            )

    return results


def load_strategy(strategy_class_path: str, config: StrategyConfig, event_bus: EventBus) -> BaseStrategy:
    """Dynamically import and instantiate a strategy from an import path."""

    module_name, class_name = strategy_class_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    strategy_class = getattr(module, class_name)

    if not inspect.isclass(strategy_class) or not issubclass(strategy_class, BaseStrategy):
        raise TypeError(f"Class is not a BaseStrategy: {strategy_class_path}")

    strategy = strategy_class(config=config, event_bus=event_bus)
    validate_strategy(strategy)

    dataset_id = str(config.parameters.get("dataset_id", "default"))
    version_hash = compute_version_hash(strategy_class, config.parameters, dataset_id)
    config.version_hash = version_hash

    _loaded_strategies[config.strategy_id] = StrategyMeta(
        strategy_id=config.strategy_id,
        strategy_class=strategy_class_path,
        version=getattr(strategy_class, "version", "0.0.0"),
        version_hash=version_hash,
        status="loaded",
    )
    return strategy


def validate_strategy(strategy: BaseStrategy) -> None:
    """Verify strategy implementation fulfills abstract contract."""

    if inspect.isabstract(strategy.__class__):
        raise TypeError(f"Strategy is abstract: {strategy.__class__.__name__}")

    required_methods = ("on_tick", "on_bar_close")
    for method_name in required_methods:
        method = getattr(strategy, method_name, None)
        if method is None or not inspect.iscoroutinefunction(method):
            raise TypeError(f"Strategy missing async method: {method_name}")


def compute_version_hash(strategy_class: type[BaseStrategy], params: dict[str, Any], dataset_id: str) -> str:
    """Generate a reproducible strategy hash from code and parameters."""

    source = inspect.getsource(strategy_class)
    payload = {
        "source": source,
        "params": params,
        "dataset_id": dataset_id,
    }
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_loaded_strategies() -> dict[str, StrategyMeta]:
    """Return loaded strategy metadata keyed by strategy id."""

    return dict(_loaded_strategies)
