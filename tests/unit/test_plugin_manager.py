from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from core.config_models import StrategyConfig
from core.event_bus import EventBus
from core.plugin_manager import compute_version_hash, discover_strategies, load_strategy


def _create_strategy_package(tmp_path: Path) -> Path:
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    (strategies_dir / "__init__.py").write_text("", encoding="utf-8")
    return strategies_dir


def _activate_tmp_strategy_package(tmp_path: Path) -> None:
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    for name in list(sys.modules):
        if name == "strategies" or name.startswith("strategies."):
            del sys.modules[name]
    importlib.invalidate_caches()


def test_discover_strategy(tmp_path: Path) -> None:
    strategies_dir = _create_strategy_package(tmp_path)
    (strategies_dir / "ema_cross.py").write_text(
        """
from core.base_strategy import BaseStrategy


class EMACross(BaseStrategy):
    strategy_id = "ema_cross"
    version = "1.0.0"

    async def on_tick(self, event):
        return None

    async def on_bar_close(self, event):
        return None
""".strip(),
        encoding="utf-8",
    )

    _activate_tmp_strategy_package(tmp_path)
    discovered = discover_strategies(strategies_dir)
    assert len(discovered) == 1
    assert discovered[0].strategy_id == "ema_cross"


def test_reject_abstract_strategy(tmp_path: Path) -> None:
    strategies_dir = _create_strategy_package(tmp_path)
    (strategies_dir / "broken.py").write_text(
        """
from core.base_strategy import BaseStrategy


class BrokenStrategy(BaseStrategy):
    strategy_id = "broken"
    version = "1.0.0"

    async def on_tick(self, event):
        return None
""".strip(),
        encoding="utf-8",
    )

    _activate_tmp_strategy_package(tmp_path)

    config = StrategyConfig(
        strategy_id="broken",
        strategy_class="strategies.broken.BrokenStrategy",
        enabled=True,
        symbols=["EURUSD"],
        timeframes=["M5"],
        parameters={},
    )

    with pytest.raises(TypeError):
        load_strategy(config.strategy_class, config, EventBus())


def test_hash_is_reproducible(tmp_path: Path) -> None:
    strategies_dir = _create_strategy_package(tmp_path)
    strategy_file = strategies_dir / "simple.py"
    strategy_file.write_text(
        """
from core.base_strategy import BaseStrategy


class SimpleStrategy(BaseStrategy):
    strategy_id = "simple"
    version = "1.0.0"

    async def on_tick(self, event):
        return None

    async def on_bar_close(self, event):
        return None
""".strip(),
        encoding="utf-8",
    )

    _activate_tmp_strategy_package(tmp_path)
    module = importlib.import_module("strategies.simple")
    strategy_class = module.SimpleStrategy

    params = {"fast": 10, "slow": 20}
    h1 = compute_version_hash(strategy_class, params, "dataset-1")
    h2 = compute_version_hash(strategy_class, params, "dataset-1")

    assert h1 == h2


def test_hash_changes_when_params_change(tmp_path: Path) -> None:
    strategies_dir = _create_strategy_package(tmp_path)
    strategy_file = strategies_dir / "simple_alt.py"
    strategy_file.write_text(
        """
from core.base_strategy import BaseStrategy


class SimpleAltStrategy(BaseStrategy):
    strategy_id = "simple_alt"
    version = "1.0.0"

    async def on_tick(self, event):
        return None

    async def on_bar_close(self, event):
        return None
""".strip(),
        encoding="utf-8",
    )

    _activate_tmp_strategy_package(tmp_path)
    module = importlib.import_module("strategies.simple_alt")
    strategy_class = module.SimpleAltStrategy

    h1 = compute_version_hash(strategy_class, {"fast": 10}, "dataset-1")
    h2 = compute_version_hash(strategy_class, {"fast": 11}, "dataset-1")

    assert h1 != h2
