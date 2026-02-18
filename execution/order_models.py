"""OMS order, fill, position, and account domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from data.asset_types import AssetClass
from risk.risk_models import OrderSide, OrderType


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""

    return datetime.now(UTC)


class OrderStatus(StrEnum):
    """Order lifecycle states."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionStatus(StrEnum):
    """Position lifecycle states."""

    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class Order(BaseModel):
    """Order model tracked by OMS."""

    order_id: str = Field(default_factory=lambda: str(uuid4()))
    broker_order_id: str | None = None
    client_order_id: str
    signal_id: str
    risk_check_id: str
    symbol: str
    broker: str
    side: OrderSide
    order_type: OrderType
    quantity: float = Field(gt=0.0)
    price: float | None = Field(default=None, gt=0.0)
    stop_price: float | None = Field(default=None, gt=0.0)
    stop_loss: float | None = Field(default=None, gt=0.0)
    take_profit: float | None = Field(default=None, gt=0.0)
    trailing_stop: float | None = Field(default=None, ge=0.0)
    time_in_force: str = "GTC"
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    filled_quantity: float = Field(default=0.0, ge=0.0)
    average_fill_price: float | None = Field(default=None, gt=0.0)
    commission: float = Field(default=0.0, ge=0.0)
    slippage: float = Field(default=0.0, ge=0.0)
    reject_reason: str | None = None
    retry_count: int = Field(default=0, ge=0)
    is_paper: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at", "submitted_at", "filled_at", "cancelled_at")
    @classmethod
    def ensure_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)


class Fill(BaseModel):
    """One execution fill event."""

    fill_id: str = Field(default_factory=lambda: str(uuid4()))
    order_id: str
    broker_fill_id: str | None = None
    symbol: str
    broker: str
    side: OrderSide
    quantity: float = Field(gt=0.0)
    price: float = Field(gt=0.0)
    commission: float = Field(default=0.0, ge=0.0)
    timestamp: datetime = Field(default_factory=utc_now)
    is_partial: bool = False
    is_paper: bool = False

    @field_validator("timestamp")
    @classmethod
    def ensure_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class Position(BaseModel):
    """Open or closed position managed by OMS."""

    position_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    broker: str
    side: OrderSide
    quantity: float = Field(gt=0.0)
    entry_price: float = Field(gt=0.0)
    current_price: float = Field(gt=0.0)
    stop_loss: float | None = Field(default=None, gt=0.0)
    take_profit: float | None = Field(default=None, gt=0.0)
    trailing_stop_price: float | None = Field(default=None, gt=0.0)
    status: PositionStatus = PositionStatus.OPEN
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None
    close_price: float | None = Field(default=None, gt=0.0)
    unrealized_pnl: float = 0.0
    realized_pnl: float | None = None
    commission_total: float = 0.0
    signal_id: str
    strategy_id: str
    asset_class: AssetClass = AssetClass.UNKNOWN
    is_paper: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("opened_at", "closed_at")
    @classmethod
    def ensure_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @property
    def pnl_pct(self) -> float:
        """PnL as percentage of entry value."""

        if self.entry_price <= 0:
            return 0.0
        if self.side == OrderSide.BUY:
            return ((self.current_price - self.entry_price) / self.entry_price) * 100.0
        return ((self.entry_price - self.current_price) / self.entry_price) * 100.0

    @property
    def r_multiple(self) -> float | None:
        """PnL expressed as multiples of initial risk (R)."""

        if self.stop_loss is None:
            return None
        risk_per_unit = abs(self.entry_price - self.stop_loss)
        if risk_per_unit <= 0:
            return None
        price_move = (
            (self.close_price if self.close_price is not None else self.current_price) - self.entry_price
            if self.side == OrderSide.BUY
            else self.entry_price - (self.close_price if self.close_price is not None else self.current_price)
        )
        return price_move / risk_per_unit


class Account(BaseModel):
    """Trading account snapshot."""

    account_id: str
    broker: str
    balance: float
    equity: float | None = None
    margin_used: float = 0.0
    margin_free: float = 0.0
    currency: str = "USD"
    is_paper: bool = False
    leverage: float = 1.0
    unrealized_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("updated_at")
    @classmethod
    def ensure_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ensure_equity(self) -> Account:
        self.equity = self.balance + self.unrealized_pnl
        self.margin_free = max(self.equity - self.margin_used, 0.0)
        return self


for _model in (Order, Fill, Position, Account):
    _model.model_config = {"extra": "forbid"}


__all__ = [
    "OrderStatus",
    "PositionStatus",
    "Order",
    "Fill",
    "Position",
    "Account",
]
