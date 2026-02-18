"""Risk-domain models and enums for module 4."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""

    return datetime.now(UTC)


class OrderSide(StrEnum):
    """Order direction."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Supported order types."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class PositionSizingMethod(StrEnum):
    """Supported position sizing methods."""

    FIXED_UNITS = "fixed_units"
    FIXED_AMOUNT = "fixed_amount"
    PERCENT_EQUITY = "percent_equity"
    PERCENT_RISK = "percent_risk"
    ATR_BASED = "atr_based"
    KELLY_FRACTIONAL = "kelly_fractional"


class RiskCheckStatus(StrEnum):
    """Risk check decision."""

    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class RiskCheck(BaseModel):
    """Result of validating one signal under risk rules."""

    check_id: str = Field(default_factory=lambda: str(uuid4()))
    signal_id: str
    symbol: str
    broker: str
    timestamp: datetime = Field(default_factory=utc_now)
    status: RiskCheckStatus

    approved_size: float | None = Field(default=None, ge=0.0)
    approved_side: OrderSide | None = None
    suggested_sl: float | None = Field(default=None, gt=0.0)
    suggested_tp: float | None = Field(default=None, gt=0.0)
    suggested_trailing: float | None = Field(default=None, ge=0.0)
    risk_amount: float | None = Field(default=None, ge=0.0)
    risk_percent: float | None = Field(default=None, ge=0.0)
    reward_risk_ratio: float | None = Field(default=None, ge=0.0)

    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    portfolio_snapshot: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def ensure_timestamp_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ensure_consistency(self) -> RiskCheck:
        if self.status == RiskCheckStatus.REJECTED and self.approved_size not in (None, 0.0):
            self.approved_size = 0.0
        if self.status in {RiskCheckStatus.APPROVED, RiskCheckStatus.MODIFIED} and self.approved_side is None:
            raise ValueError("approved_side is required when status is approved or modified")
        if self.status == RiskCheckStatus.REJECTED and not self.rejection_reasons:
            self.rejection_reasons = ["risk_rejected"]
        return self


class PositionSize(BaseModel):
    """Output of a position sizing calculation."""

    method: PositionSizingMethod
    units: float = Field(ge=0.0)
    notional_value: float = Field(ge=0.0)
    risk_amount: float = Field(ge=0.0)
    risk_percent: float = Field(ge=0.0)
    max_allowed_units: float = Field(ge=0.0)
    was_capped: bool = False
    cap_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_cap_reason(self) -> PositionSize:
        if self.was_capped and not self.cap_reason:
            raise ValueError("cap_reason is required when was_capped=True")
        return self


class RiskReport(BaseModel):
    """Portfolio-level risk snapshot."""

    timestamp: datetime = Field(default_factory=utc_now)
    run_id: str

    equity: float
    balance: float
    unrealized_pnl: float
    realized_pnl_today: float
    realized_pnl_week: float

    daily_drawdown_pct: float = Field(ge=0.0)
    weekly_drawdown_pct: float = Field(ge=0.0)
    max_drawdown_pct: float = Field(ge=0.0)
    current_drawdown_pct: float = Field(ge=0.0)

    open_positions_count: int = Field(ge=0)
    total_exposure_notional: float = Field(ge=0.0)
    total_exposure_pct: float = Field(ge=0.0)
    exposure_by_asset: dict[str, float] = Field(default_factory=dict)
    exposure_by_asset_class: dict[str, float] = Field(default_factory=dict)

    limits_status: dict[str, dict[str, float]] = Field(default_factory=dict)
    kill_switch_active: bool = False
    kill_switch_reasons: list[str] = Field(default_factory=list)

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


for _model in (RiskCheck, PositionSize, RiskReport):
    _model.model_config = {"extra": "forbid"}


__all__ = [
    "OrderSide",
    "OrderType",
    "PositionSizingMethod",
    "RiskCheckStatus",
    "RiskCheck",
    "PositionSize",
    "RiskReport",
]
