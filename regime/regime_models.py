"""Market regime models and enums."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TrendRegime(StrEnum):
    STRONG_UPTREND = "strong_uptrend"
    WEAK_UPTREND = "weak_uptrend"
    RANGING = "ranging"
    WEAK_DOWNTREND = "weak_downtrend"
    STRONG_DOWNTREND = "strong_downtrend"


class VolatilityRegime(StrEnum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class LiquidityRegime(StrEnum):
    LIQUID = "liquid"
    THIN = "thin"
    ILLIQUID = "illiquid"


class MarketRegime(BaseModel):
    """Unified market regime snapshot."""

    symbol: str
    timeframe: str
    timestamp: datetime
    trend: TrendRegime
    volatility: VolatilityRegime
    liquidity: LiquidityRegime
    is_tradeable: bool
    no_trade_reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_strategies: list[str] = Field(default_factory=list)
    description: str
    metrics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


__all__ = [
    "TrendRegime",
    "VolatilityRegime",
    "LiquidityRegime",
    "MarketRegime",
]
