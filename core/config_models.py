"""Configuration models for the trading core."""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class Environment(StrEnum):
    """Runtime environment modes."""

    DEVELOPMENT = "development"
    PAPER = "paper"
    LIVE = "live"


class LogLevel(StrEnum):
    """Supported logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class EventBusBackendType(StrEnum):
    """Event bus backend selector."""

    ASYNCIO = "asyncio"
    REDIS = "redis"


class IndicatorBackendPreference(StrEnum):
    """Preferred indicator backend."""

    AUTO = "auto"
    TALIB = "talib"
    PANDAS_TA = "pandas_ta"
    TA = "ta"
    CUSTOM = "custom"


class SystemConfig(BaseModel):
    """Global system configuration."""

    run_id: str | None = None
    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    event_bus_backend: EventBusBackendType = EventBusBackendType.ASYNCIO
    redis_url: str | None = None
    snapshot_interval_seconds: int = Field(default=300, ge=1)
    timezone: str = "UTC"
    data_store_path: str = "./data_store"

    @model_validator(mode="after")
    def ensure_run_id(self) -> SystemConfig:
        if not self.run_id:
            self.run_id = str(uuid4())
        return self


class BrokerConfig(BaseModel):
    """Broker integration configuration without credentials."""

    broker_id: str
    broker_type: str
    enabled: bool
    paper_mode: bool
    extra: dict[str, object] = Field(default_factory=dict)


class StrategyConfig(BaseModel):
    """Runtime strategy configuration."""

    strategy_id: str
    strategy_class: str
    enabled: bool
    symbols: list[str]
    timeframes: list[str]
    parameters: dict[str, object] = Field(default_factory=dict)
    version_hash: str | None = None


class IndicatorSpec(BaseModel):
    """One indicator declaration in YAML."""

    id: str
    params: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True


class IndicatorGroupsConfig(BaseModel):
    """Indicator groups by analytic domain."""

    trend: list[IndicatorSpec] = Field(default_factory=list)
    momentum: list[IndicatorSpec] = Field(default_factory=list)
    volatility: list[IndicatorSpec] = Field(default_factory=list)
    volume: list[IndicatorSpec] = Field(default_factory=list)
    patterns: list[IndicatorSpec] = Field(default_factory=list)


class IndicatorProfileOverride(IndicatorGroupsConfig):
    """Per-profile indicator override block."""

    enabled: bool = True


class IndicatorEngineConfig(BaseModel):
    """Runtime settings for indicator engine."""

    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=60, ge=1)
    max_lookback_bars: int = Field(default=1000, ge=50)
    backend_preference: IndicatorBackendPreference = IndicatorBackendPreference.AUTO


class RegimeConfig(BaseModel):
    """Runtime settings for market regime detection."""

    enabled: bool = True
    min_bars_for_detection: int = Field(default=100, ge=20)
    hurst_lags: dict[str, int] = Field(default_factory=lambda: {"min": 2, "max": 20})
    adx_trending_threshold: float = 25.0
    adx_ranging_threshold: float = 20.0
    atr_lookback_bars: int = Field(default=200, ge=50)
    spread_spike_multiplier: float = Field(default=3.0, ge=1.0)
    news_window_minutes_before: int = Field(default=30, ge=0)
    news_window_minutes_after: int = Field(default=15, ge=0)
    regime_change_cooldown_bars: int = Field(default=3, ge=0)


class IndicatorsConfig(BaseModel):
    """Merged indicator and regime configuration."""

    indicator_engine: IndicatorEngineConfig = Field(default_factory=IndicatorEngineConfig)
    defaults: IndicatorGroupsConfig = Field(default_factory=IndicatorGroupsConfig)
    overrides: dict[str, IndicatorProfileOverride] = Field(default_factory=dict)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)


class SignalEnsembleMethod(StrEnum):
    """Supported ensemble methods."""

    WEIGHTED_VOTE = "weighted_vote"
    MAJORITY_VOTE = "majority_vote"
    UNANIMOUS = "unanimous"
    BEST_CONFIDENCE = "best_confidence"
    REGIME_WEIGHTED = "regime_weighted"


class SignalEngineConfig(BaseModel):
    """Core runtime settings for signal engine."""

    enabled: bool = True
    default_lookback_bars: int = Field(default=500, ge=50)
    signal_expiry_minutes: int = Field(default=120, ge=1)
    signal_history_limit: int = Field(default=500, ge=10)
    emit_on_bar_close: bool = True


class SignalStrategyConfig(BaseModel):
    """One built-in strategy declaration used by signal engine."""

    strategy_id: str
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.45, ge=0.0, le=1.0)
    compatible_asset_classes: list[str] = Field(default_factory=list)
    compatible_regimes: list[str] = Field(default_factory=list)
    horizons: list[str] = Field(default_factory=list)
    params: dict[str, object] = Field(default_factory=dict)


class EnsembleConfig(BaseModel):
    """Ensemble combination settings."""

    method: SignalEnsembleMethod = SignalEnsembleMethod.WEIGHTED_VOTE
    tie_breaker: SignalEnsembleMethod = SignalEnsembleMethod.REGIME_WEIGHTED
    wait_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    contradiction_threshold: float = Field(default=0.50, ge=0.0, le=1.0)


class ConfidenceConfig(BaseModel):
    """Confidence post-processing penalties and display thresholds."""

    contradiction_penalty: float = Field(default=0.20, ge=0.0, le=1.0)
    regime_mismatch_penalty: float = Field(default=0.25, ge=0.0, le=1.0)
    non_trade_penalty: float = Field(default=0.35, ge=0.0, le=1.0)
    strong_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    moderate_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    weak_threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    extreme_volatility_cap: float = Field(default=0.30, ge=0.0, le=1.0)
    illiquid_cap: float = Field(default=0.20, ge=0.0, le=1.0)


class FiltersConfig(BaseModel):
    """Enable/disable filters and thresholds."""

    regime_filter: bool = True
    news_filter: bool = True
    session_filter: bool = True
    spread_filter: bool = True
    correlation_filter: bool = True
    max_spread_multiplier: float = Field(default=3.0, ge=1.0)
    correlation_window_minutes: int = Field(default=60, ge=1)
    correlation_group_limit: int = Field(default=2, ge=1)


class AntiOvertradingConfig(BaseModel):
    """Controls repeated-signal suppression."""

    enabled: bool = True
    cooldown_bars: int = Field(default=3, ge=0)
    max_signals_per_hour: int = Field(default=4, ge=1)
    consecutive_loss_pause_count: int = Field(default=3, ge=1)
    pause_hours: int = Field(default=2, ge=1)


class HorizonConfig(BaseModel):
    """Natural-language horizon parsing defaults."""

    default_timeframe: str = "H1"
    default_horizon: str = "2h"
    allow_relative_words: bool = True


class NotificationsConfig(BaseModel):
    """Optional outbound notification channels."""

    enabled: bool = False
    telegram_enabled: bool = False
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None


class BackvalidationConfig(BaseModel):
    """Relative robust gate thresholds for signal validation."""

    min_trades: int = Field(default=30, ge=1)
    min_relative_delta: float = Field(default=0.03, ge=0.0, le=1.0)
    min_profit_factor: float = Field(default=1.0, ge=0.0)


def _default_signal_strategies() -> list[SignalStrategyConfig]:
    return [
        SignalStrategyConfig(strategy_id="trend_following", weight=0.20),
        SignalStrategyConfig(strategy_id="mean_reversion", weight=0.18),
        SignalStrategyConfig(strategy_id="momentum_breakout", weight=0.16),
        SignalStrategyConfig(strategy_id="scalping_reversal", weight=0.12),
        SignalStrategyConfig(strategy_id="swing_composite", weight=0.14),
        SignalStrategyConfig(strategy_id="investment_fundamental", weight=0.08),
        SignalStrategyConfig(strategy_id="range_scalp", weight=0.12),
    ]


class SignalsConfig(BaseModel):
    """Signal engine module configuration."""

    enabled: bool = True
    engine: SignalEngineConfig = Field(default_factory=SignalEngineConfig)
    strategies: list[SignalStrategyConfig] = Field(default_factory=_default_signal_strategies)
    ensemble: EnsembleConfig = Field(default_factory=EnsembleConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    anti_overtrading: AntiOvertradingConfig = Field(default_factory=AntiOvertradingConfig)
    horizon: HorizonConfig = Field(default_factory=HorizonConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    backvalidation: BackvalidationConfig = Field(default_factory=BackvalidationConfig)


class RiskSizingMethod(StrEnum):
    """Supported position sizing methods for risk module."""

    FIXED_UNITS = "fixed_units"
    FIXED_AMOUNT = "fixed_amount"
    PERCENT_EQUITY = "percent_equity"
    PERCENT_RISK = "percent_risk"
    ATR_BASED = "atr_based"
    KELLY_FRACTIONAL = "kelly_fractional"


class SlippageMethod(StrEnum):
    """Supported slippage models."""

    FIXED_PIPS = "fixed_pips"
    PERCENT = "percent"
    SPREAD_BASED = "spread_based"
    VOLATILITY_BASED = "volatility_based"


class CommissionMethod(StrEnum):
    """Supported commission models."""

    PER_LOT = "per_lot"
    PERCENT = "percent"
    PER_SHARE = "per_share"
    FIXED = "fixed"
    ZERO = "zero"


class TrailingStopMethod(StrEnum):
    """Supported trailing stop behaviors."""

    FIXED_DISTANCE = "fixed_distance"
    ATR_BASED = "atr_based"
    BREAKEVEN = "breakeven"
    STEP = "step"


class StopLossMethod(StrEnum):
    """Supported stop-loss calculation methods."""

    ATR_BASED = "atr_based"
    FIXED_PIPS = "fixed_pips"
    SUPPORT_RESISTANCE = "support_resistance"
    PERCENT = "percent"
    CHANDELIER = "chandelier"


class TakeProfitMethod(StrEnum):
    """Supported take-profit calculation methods."""

    RISK_REWARD = "risk_reward"
    FIXED_PIPS = "fixed_pips"
    SUPPORT_RESISTANCE = "support_resistance"
    ATR_BASED = "atr_based"


class SizingOverrideConfig(BaseModel):
    """Per-asset sizing override."""

    method: RiskSizingMethod
    amount: float | None = Field(default=None, ge=0.0)
    pct: float | None = Field(default=None, ge=0.0)
    risk_pct: float | None = Field(default=None, ge=0.0)


class ExposureLimitsConfig(BaseModel):
    """Exposure limits used by risk checks."""

    max_exposure_per_symbol_pct: float = Field(default=10.0, ge=0.0)
    max_exposure_per_asset_class_pct: float = Field(default=30.0, ge=0.0)
    max_correlated_exposure_pct: float = Field(default=20.0, ge=0.0)


class RiskLimitsConfig(BaseModel):
    """Global hard risk limits."""

    max_daily_drawdown_pct: float = Field(default=3.0, ge=0.0)
    max_weekly_drawdown_pct: float = Field(default=7.0, ge=0.0)
    max_open_positions: int = Field(default=5, ge=1)
    max_exposure_per_symbol_pct: float = Field(default=10.0, ge=0.0)
    max_exposure_per_asset_class_pct: float = Field(default=30.0, ge=0.0)
    max_correlated_exposure_pct: float = Field(default=20.0, ge=0.0)
    min_equity_threshold_pct: float = Field(default=70.0, ge=0.0, le=100.0)

    def to_exposure_limits(self) -> ExposureLimitsConfig:
        """Return exposure-only subset."""

        return ExposureLimitsConfig(
            max_exposure_per_symbol_pct=self.max_exposure_per_symbol_pct,
            max_exposure_per_asset_class_pct=self.max_exposure_per_asset_class_pct,
            max_correlated_exposure_pct=self.max_correlated_exposure_pct,
        )


class StopConfig(BaseModel):
    """Stop-loss and take-profit configuration."""

    default_sl_method: StopLossMethod = StopLossMethod.ATR_BASED
    atr_multiplier_sl: float = Field(default=2.0, ge=0.1)
    default_tp_method: TakeProfitMethod = TakeProfitMethod.RISK_REWARD
    min_rr_ratio: float = Field(default=1.5, ge=0.1)
    trailing_stop_enabled: bool = True
    trailing_stop_method: TrailingStopMethod = TrailingStopMethod.ATR_BASED
    trailing_atr_multiplier: float = Field(default=1.5, ge=0.1)


class TrailingConfig(BaseModel):
    """Runtime trailing-stop behavior."""

    method: TrailingStopMethod = TrailingStopMethod.ATR_BASED
    atr_multiplier: float = Field(default=1.5, ge=0.1)
    fixed_distance_pips: float = Field(default=10.0, ge=0.0)
    breakeven_r_multiple: float = Field(default=1.0, ge=0.0)
    step_r_multiple: float = Field(default=0.5, ge=0.0)


class TimeExitConfig(BaseModel):
    """Time-based forced exit settings."""

    max_hold_bars: dict[str, int] = Field(
        default_factory=lambda: {
            "M1": 30,
            "M5": 24,
            "M15": 16,
            "H1": 48,
            "H4": 20,
            "D1": 10,
        }
    )
    close_before_session_end_minutes: int = Field(default=30, ge=0)
    close_before_high_impact_news_minutes: int = Field(default=15, ge=0)
    force_end_of_day: bool = False


class SlippageConfig(BaseModel):
    """Slippage model settings."""

    method: SlippageMethod = SlippageMethod.SPREAD_BASED
    fixed_pips: float = Field(default=1.0, ge=0.0)
    percent: float = Field(default=0.001, ge=0.0)


class CommissionRuleConfig(BaseModel):
    """Commission rule for one asset class bucket."""

    method: CommissionMethod = CommissionMethod.ZERO
    amount_per_lot: float = Field(default=0.0, ge=0.0)
    pct: float = Field(default=0.0, ge=0.0)
    amount_per_share: float = Field(default=0.0, ge=0.0)
    fixed_amount: float = Field(default=0.0, ge=0.0)


class CommissionsConfig(BaseModel):
    """Commission model per asset bucket."""

    forex: CommissionRuleConfig = Field(
        default_factory=lambda: CommissionRuleConfig(method=CommissionMethod.PER_LOT, amount_per_lot=7.0)
    )
    crypto: CommissionRuleConfig = Field(
        default_factory=lambda: CommissionRuleConfig(method=CommissionMethod.PERCENT, pct=0.001)
    )
    stock: CommissionRuleConfig = Field(
        default_factory=lambda: CommissionRuleConfig(method=CommissionMethod.PER_SHARE, amount_per_share=0.01)
    )
    binary_option: CommissionRuleConfig = Field(
        default_factory=lambda: CommissionRuleConfig(method=CommissionMethod.ZERO)
    )
    fixed_term: CommissionRuleConfig = Field(
        default_factory=lambda: CommissionRuleConfig(method=CommissionMethod.ZERO)
    )


class KillSwitchConfig(BaseModel):
    """Kill switch thresholds and automation flags."""

    auto_close_positions: bool = False
    max_consecutive_losses: int = Field(default=7, ge=1)
    max_api_error_rate_pct: float = Field(default=20.0, ge=0.0)
    max_latency_ms: float = Field(default=2000.0, ge=0.0)
    max_fill_deviation_pct: float = Field(default=2.0, ge=0.0)
    max_equity_spike_pct: float = Field(default=10.0, ge=0.0)


class PaperConfig(BaseModel):
    """Paper trading runtime defaults."""

    initial_balance: float = Field(default=10_000.0, ge=0.0)
    currency: str = "USD"
    leverage: float = Field(default=100.0, ge=1.0)
    fill_mode: str = "realistic"
    partial_fill_probability: float = Field(default=0.05, ge=0.0, le=1.0)


class RiskConfig(BaseModel):
    """Risk management and OMS module configuration."""

    enabled: bool = False
    default_sizing_method: RiskSizingMethod = RiskSizingMethod.PERCENT_RISK
    default_risk_per_trade_pct: float = Field(default=1.0, ge=0.0)
    max_risk_per_trade_pct: float = Field(default=2.0, ge=0.0)
    kelly_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    sizing_overrides: dict[str, SizingOverrideConfig] = Field(default_factory=dict)

    default_sl_method: StopLossMethod = StopLossMethod.ATR_BASED
    atr_multiplier_sl: float = Field(default=2.0, ge=0.1)
    default_tp_method: TakeProfitMethod = TakeProfitMethod.RISK_REWARD
    min_rr_ratio: float = Field(default=1.5, ge=0.1)
    trailing_stop_enabled: bool = True
    trailing_stop_method: TrailingStopMethod = TrailingStopMethod.ATR_BASED
    trailing_atr_multiplier: float = Field(default=1.5, ge=0.1)

    max_hold_bars: dict[str, int] = Field(
        default_factory=lambda: {
            "M1": 30,
            "M5": 24,
            "M15": 16,
            "H1": 48,
            "H4": 20,
            "D1": 10,
        }
    )
    close_before_session_end_minutes: int = Field(default=30, ge=0)
    close_before_high_impact_news_minutes: int = Field(default=15, ge=0)

    limits: RiskLimitsConfig = Field(default_factory=RiskLimitsConfig)
    slippage: SlippageConfig = Field(default_factory=SlippageConfig)
    commissions: CommissionsConfig = Field(default_factory=CommissionsConfig)
    kill_switch: KillSwitchConfig = Field(default_factory=KillSwitchConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)

    @model_validator(mode="after")
    def ensure_max_risk(self) -> RiskConfig:
        if self.default_risk_per_trade_pct > self.max_risk_per_trade_pct:
            self.default_risk_per_trade_pct = self.max_risk_per_trade_pct
        return self

    def stop_config(self) -> StopConfig:
        """Build stop config view from root fields."""

        return StopConfig(
            default_sl_method=self.default_sl_method,
            atr_multiplier_sl=self.atr_multiplier_sl,
            default_tp_method=self.default_tp_method,
            min_rr_ratio=self.min_rr_ratio,
            trailing_stop_enabled=self.trailing_stop_enabled,
            trailing_stop_method=self.trailing_stop_method,
            trailing_atr_multiplier=self.trailing_atr_multiplier,
        )

    def trailing_config(self) -> TrailingConfig:
        """Build trailing config view from root fields."""

        return TrailingConfig(
            method=self.trailing_stop_method,
            atr_multiplier=self.trailing_atr_multiplier,
        )

    def time_exit_config(self) -> TimeExitConfig:
        """Build time-exit config view from root fields."""

        return TimeExitConfig(
            max_hold_bars=self.max_hold_bars,
            close_before_session_end_minutes=self.close_before_session_end_minutes,
            close_before_high_impact_news_minutes=self.close_before_high_impact_news_minutes,
        )


class RootConfig(BaseModel):
    """Root merged configuration."""

    system: SystemConfig
    brokers: list[BrokerConfig] = Field(default_factory=list)
    strategies: list[StrategyConfig] = Field(default_factory=list)
    indicators: IndicatorsConfig = Field(default_factory=IndicatorsConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)


for model in (
    SystemConfig,
    BrokerConfig,
    StrategyConfig,
    IndicatorSpec,
    IndicatorGroupsConfig,
    IndicatorProfileOverride,
    IndicatorEngineConfig,
    RegimeConfig,
    IndicatorsConfig,
    SignalEngineConfig,
    SignalStrategyConfig,
    EnsembleConfig,
    ConfidenceConfig,
    FiltersConfig,
    AntiOvertradingConfig,
    HorizonConfig,
    NotificationsConfig,
    BackvalidationConfig,
    SignalsConfig,
    SizingOverrideConfig,
    ExposureLimitsConfig,
    RiskLimitsConfig,
    StopConfig,
    TrailingConfig,
    TimeExitConfig,
    SlippageConfig,
    CommissionRuleConfig,
    CommissionsConfig,
    KillSwitchConfig,
    PaperConfig,
    RiskConfig,
    RootConfig,
):
    model.model_config = {"extra": "forbid"}
