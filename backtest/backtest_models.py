"""Domain models for module 5 backtesting and replay."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from data.asset_types import AssetClass
from risk.risk_models import OrderSide


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BacktestMode(StrEnum):
    """Supported backtest execution modes."""

    SIMPLE = "simple"
    WALK_FORWARD = "walk_forward"
    OUT_OF_SAMPLE = "out_of_sample"


class BacktestConfig(BaseModel):
    """Complete runtime configuration for one backtest run."""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_ids: list[str]
    symbols: list[str]
    brokers: list[str]
    timeframes: list[str]
    asset_classes: list[AssetClass] = Field(default_factory=list)
    start_date: datetime
    end_date: datetime
    mode: BacktestMode = BacktestMode.SIMPLE
    wf_train_periods: int = Field(default=12, ge=1)
    wf_test_periods: int = Field(default=3, ge=1)
    wf_step_periods: int = Field(default=3, ge=1)
    oos_pct: float = Field(default=0.20, gt=0.0, lt=1.0)
    purge_bars: int = Field(default=10, ge=0)
    initial_capital: float = Field(default=10000.0, gt=0.0)
    currency: str = "USD"
    use_realistic_fills: bool = True
    risk_config: dict[str, Any] = Field(default_factory=dict)
    optimize_params: dict[str, tuple[float, float, float]] = Field(default_factory=dict)
    optimize_metric: str = "sharpe_ratio"
    warmup_bars: int = Field(default=200, ge=0)

    @field_validator("start_date", "end_date")
    @classmethod
    def _ensure_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_dates(self) -> BacktestConfig:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be greater than start_date")
        return self


class BacktestTrade(BaseModel):
    """One simulated trade generated during a backtest."""

    trade_id: str
    symbol: str
    strategy_id: str
    side: OrderSide
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_net: float
    commission: float
    slippage: float
    bars_held: int
    exit_reason: str
    r_multiple: float | None = None
    stop_loss: float | None = None
    regime_at_entry: str = "unknown"
    volatility_at_entry: str = "unknown"
    signal_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0

    @field_validator("entry_time", "exit_time")
    @classmethod
    def _ensure_trade_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("trade datetime must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_time_order(self) -> BacktestTrade:
        if self.exit_time < self.entry_time:
            raise ValueError("exit_time must be greater than or equal to entry_time")
        if self.r_multiple is None and self.stop_loss is not None:
            risk_per_unit = abs(self.entry_price - self.stop_loss)
            if risk_per_unit > 0:
                direction = 1.0 if self.side == OrderSide.BUY else -1.0
                price_move = (self.exit_price - self.entry_price) * direction
                self.r_multiple = price_move / risk_per_unit
        return self


class BacktestMetrics(BaseModel):
    """Performance metrics summary."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    breakeven_trades: int = 0
    total_pnl: float = 0.0
    total_pnl_net: float = 0.0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    avg_pnl_per_trade: float = 0.0
    avg_pnl_winners: float = 0.0
    avg_pnl_losers: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    payoff_ratio: float = 0.0
    avg_r_multiple: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_bars: int = 0
    avg_drawdown_pct: float = 0.0
    ulcer_index: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    omega_ratio: float = 0.0
    longest_winning_streak: int = 0
    longest_losing_streak: int = 0
    monthly_returns: dict[str, float] = Field(default_factory=dict)
    yearly_returns: dict[str, float] = Field(default_factory=dict)
    stability_score: float = 0.0
    avg_bars_in_trade: float = 0.0
    avg_bars_between_trades: float = 0.0
    trades_per_month: float = 0.0


class WalkForwardWindow(BaseModel):
    """One train/test window in walk-forward analysis."""

    window_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_metrics: BacktestMetrics
    test_metrics: BacktestMetrics
    best_params: dict[str, Any] = Field(default_factory=dict)
    is_metrics: BacktestMetrics
    degradation_score: float | None = None

    @field_validator("train_start", "train_end", "test_start", "test_end")
    @classmethod
    def _ensure_wf_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("window datetime must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _calc_degradation(self) -> WalkForwardWindow:
        if self.degradation_score is None:
            train_sharpe = self.train_metrics.sharpe_ratio
            if abs(train_sharpe) < 1e-12:
                self.degradation_score = 0.0
            else:
                self.degradation_score = self.test_metrics.sharpe_ratio / train_sharpe
        return self


class BacktestResult(BaseModel):
    """Backtest output object used by CLIs and reports."""

    config: BacktestConfig
    metrics: BacktestMetrics
    trades: list[BacktestTrade] = Field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = Field(default_factory=list)
    drawdown_curve: list[tuple[datetime, float]] = Field(default_factory=list)
    metrics_by_strategy: dict[str, BacktestMetrics] = Field(default_factory=dict)
    metrics_by_regime: dict[str, BacktestMetrics] = Field(default_factory=dict)
    metrics_by_session: dict[str, BacktestMetrics] = Field(default_factory=dict)
    metrics_by_month: dict[str, BacktestMetrics] = Field(default_factory=dict)
    wf_windows: list[WalkForwardWindow] | None = None
    oos_metrics: BacktestMetrics | None = None
    is_metrics: BacktestMetrics | None = None
    computed_at: datetime = Field(default_factory=_utc_now)
    duration_seconds: float = 0.0

    @field_validator("computed_at")
    @classmethod
    def _ensure_computed_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("computed_at must be timezone-aware")
        return value.astimezone(UTC)


class OptimizationResult(BaseModel):
    """Optimization output with anti-overfit diagnostics."""

    strategy_id: str
    best_params: dict[str, Any] = Field(default_factory=dict)
    best_score: float = 0.0
    best_metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    n_trials: int = 0
    n_successful_trials: int = 0
    optimization_time_seconds: float = 0.0
    param_importance: dict[str, float] = Field(default_factory=dict)
    all_trials: list[dict[str, Any]] = Field(default_factory=list)
    overfitting_risk: str = "unknown"
    verdict: str = "use_defaults"


for _model in (
    BacktestConfig,
    BacktestTrade,
    BacktestMetrics,
    WalkForwardWindow,
    BacktestResult,
    OptimizationResult,
):
    _model.model_config = {"extra": "forbid"}


__all__ = [
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestMode",
    "BacktestResult",
    "BacktestTrade",
    "OptimizationResult",
    "WalkForwardWindow",
]
