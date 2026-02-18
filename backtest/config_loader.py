"""Dedicated config loader for module 5."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field


class WalkForwardDefaults(BaseModel):
    train_periods: int = Field(default=12, ge=1)
    test_periods: int = Field(default=3, ge=1)
    step_periods: int = Field(default=3, ge=1)
    min_windows: int = Field(default=3, ge=1)


class OutOfSampleDefaults(BaseModel):
    oos_pct: float = Field(default=0.20, gt=0.0, lt=1.0)
    purge_bars: int = Field(default=10, ge=0)
    embargo_bars: int = Field(default=5, ge=0)


class OptimizerDefaults(BaseModel):
    n_trials: int = Field(default=100, ge=1)
    n_jobs: int = 1
    default_metric: str = "sharpe_ratio"
    lambda_complexity: float = Field(default=0.05, ge=0.0)
    mu_instability: float = Field(default=0.10, ge=0.0)
    max_params_to_optimize: int = Field(default=6, ge=1)


class ViabilityThresholds(BaseModel):
    min_profit_factor: float = Field(default=1.30, ge=0.0)
    min_sharpe_ratio: float = Field(default=0.80)
    max_drawdown_pct: float = Field(default=25.0, ge=0.0)
    min_win_rate: float = Field(default=0.40, ge=0.0, le=1.0)
    min_trades: int = Field(default=30, ge=1)


class ReportDefaults(BaseModel):
    output_dir: str = "reports"
    generate_html: bool = True
    generate_pdf: bool = True
    embed_charts: bool = True
    include_all_trades: bool = True


class BacktestDefaults(BaseModel):
    default_initial_capital: float = Field(default=10000.0, gt=0.0)
    default_currency: str = "USD"
    use_realistic_fills: bool = True
    warmup_bars: int = Field(default=200, ge=0)
    random_seed: int = 42
    walk_forward: WalkForwardDefaults = Field(default_factory=WalkForwardDefaults)
    out_of_sample: OutOfSampleDefaults = Field(default_factory=OutOfSampleDefaults)
    optimizer: OptimizerDefaults = Field(default_factory=OptimizerDefaults)
    viability_thresholds: ViabilityThresholds = Field(default_factory=ViabilityThresholds)
    report: ReportDefaults = Field(default_factory=ReportDefaults)


class ReplayDefaults(BaseModel):
    default_speed: float = Field(default=1.0, gt=0.0)
    default_warmup_bars: int = Field(default=200, ge=0)
    save_replay_session: bool = False


class ShadowDefaults(BaseModel):
    enabled: bool = False
    log_all_signals: bool = True
    compare_with_live_interval_minutes: int = Field(default=60, ge=1)


class BacktestModuleConfig(BaseModel):
    backtest: BacktestDefaults = Field(default_factory=BacktestDefaults)
    replay: ReplayDefaults = Field(default_factory=ReplayDefaults)
    shadow: ShadowDefaults = Field(default_factory=ShadowDefaults)


for _model in (
    WalkForwardDefaults,
    OutOfSampleDefaults,
    OptimizerDefaults,
    ViabilityThresholds,
    ReportDefaults,
    BacktestDefaults,
    ReplayDefaults,
    ShadowDefaults,
    BacktestModuleConfig,
):
    _model.model_config = {"extra": "forbid"}


def load_backtest_config(path: Path = Path("config/backtest.yaml")) -> BacktestModuleConfig:
    """Load module 5 config with safe defaults and ATP_* overrides."""

    payload: dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
    _apply_overrides(payload)
    return BacktestModuleConfig.model_validate(payload)


def save_backtest_config(config: BacktestModuleConfig, path: Path = Path("config/backtest.yaml")) -> None:
    """Persist module 5 config to YAML."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8")


def _apply_overrides(payload: dict[str, Any]) -> None:
    prefixes = ("ATP_BACKTEST__", "ATP_REPLAY__", "ATP_SHADOW__")
    for env_key, raw_value in os.environ.items():
        selected = next((p for p in prefixes if env_key.startswith(p)), None)
        if selected is None:
            continue
        parsed_value = yaml.safe_load(raw_value) if raw_value else raw_value
        if selected == "ATP_BACKTEST__":
            base_path = ["backtest"]
        elif selected == "ATP_REPLAY__":
            base_path = ["replay"]
        else:
            base_path = ["shadow"]

        parts = base_path + env_key[len(selected) :].lower().split("__")
        cursor = payload
        for part in parts[:-1]:
            node = cursor.get(part)
            if not isinstance(node, dict):
                node = {}
                cursor[part] = node
            cursor = node
        cursor[parts[-1]] = parsed_value


__all__ = [
    "BacktestModuleConfig",
    "load_backtest_config",
    "save_backtest_config",
]
