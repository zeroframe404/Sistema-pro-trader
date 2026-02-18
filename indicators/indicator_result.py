"""Unified indicator result models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IndicatorValue(BaseModel):
    """Single indicator value at one timestamp."""

    name: str
    value: float | None
    timestamp: datetime
    is_valid: bool
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class IndicatorSeries(BaseModel):
    """Full indicator output across a bar series."""

    indicator_id: str
    symbol: str
    timeframe: str
    values: list[IndicatorValue] = Field(default_factory=list)
    warmup_period: int
    computed_at: datetime = Field(default_factory=_utc_now)
    parameters: dict[str, Any] = Field(default_factory=dict)
    backend_used: str

    @field_validator("computed_at")
    @classmethod
    def ensure_computed_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("computed_at must be timezone-aware")
        return value.astimezone(UTC)
