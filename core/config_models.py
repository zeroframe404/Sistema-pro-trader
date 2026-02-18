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


class SystemConfig(BaseModel):
    """Global system configuration."""

    run_id: str | None = None
    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    event_bus_backend: EventBusBackendType = EventBusBackendType.ASYNCIO
    redis_url: str | None = None
    snapshot_interval_seconds: int = Field(default=300, ge=1)
    timezone: str = "UTC"

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


class StrategyConfig(BaseModel):
    """Runtime strategy configuration."""

    strategy_id: str
    strategy_class: str
    enabled: bool
    symbols: list[str]
    timeframes: list[str]
    parameters: dict[str, object] = Field(default_factory=dict)
    version_hash: str | None = None


class RootConfig(BaseModel):
    """Root merged configuration."""

    system: SystemConfig
    brokers: list[BrokerConfig] = Field(default_factory=list)
    strategies: list[StrategyConfig] = Field(default_factory=list)


for model in (SystemConfig, BrokerConfig, StrategyConfig, RootConfig):
    model.model_config = {"extra": "forbid"}
