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


class RootConfig(BaseModel):
    """Root merged configuration."""

    system: SystemConfig
    brokers: list[BrokerConfig] = Field(default_factory=list)
    strategies: list[StrategyConfig] = Field(default_factory=list)
    indicators: IndicatorsConfig = Field(default_factory=IndicatorsConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)


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
    RootConfig,
):
    model.model_config = {"extra": "forbid"}
