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


class RootConfig(BaseModel):
    """Root merged configuration."""

    system: SystemConfig
    brokers: list[BrokerConfig] = Field(default_factory=list)
    strategies: list[StrategyConfig] = Field(default_factory=list)
    indicators: IndicatorsConfig = Field(default_factory=IndicatorsConfig)


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
    RootConfig,
):
    model.model_config = {"extra": "forbid"}
