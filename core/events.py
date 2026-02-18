"""Pydantic event models used across the platform."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from core.event_types import EventType


def utc_now() -> datetime:
    """Return current UTC timestamp with timezone information."""

    return datetime.now(UTC)


class BaseEvent(BaseModel):
    """Base event payload shared by all event models."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=utc_now)
    source: str
    run_id: str

    @field_validator("timestamp")
    @classmethod
    def ensure_utc_timestamp(cls, value: datetime) -> datetime:
        """Ensure event timestamps are timezone-aware and normalized to UTC."""

        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class TickEvent(BaseEvent):
    """Real-time quote update."""

    event_type: Literal[EventType.TICK] = EventType.TICK
    symbol: str
    broker: str
    bid: float
    ask: float
    last: float
    volume: float


class BarCloseEvent(BaseEvent):
    """OHLCV bar close event."""

    event_type: Literal[EventType.BAR_CLOSE] = EventType.BAR_CLOSE
    symbol: str
    broker: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp_open: datetime
    timestamp_close: datetime

    @field_validator("timestamp_open", "timestamp_close")
    @classmethod
    def ensure_bar_timestamps_are_utc(cls, value: datetime) -> datetime:
        """Ensure bar timestamps are timezone-aware and normalized to UTC."""

        if value.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")
        return value.astimezone(UTC)


class SignalEvent(BaseEvent):
    """Strategy signal generated from market data."""

    event_type: Literal[EventType.SIGNAL] = EventType.SIGNAL
    symbol: str
    broker: str
    strategy_id: str
    strategy_version: str
    direction: Literal["BUY", "SELL", "WAIT", "NO_TRADE"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    timeframe: str
    horizon: str


class OrderEvent(BaseEvent):
    """Base order payload used by order lifecycle events."""

    order_id: str
    client_order_id: str | None = None
    risk_check_id: str | None = None
    symbol: str
    broker: str
    direction: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]
    quantity: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    status: str | None = None
    is_paper: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderSubmitEvent(OrderEvent):
    """Order submit event sent to a broker adapter."""

    event_type: Literal[EventType.ORDER_SUBMIT] = EventType.ORDER_SUBMIT


class OrderFillEvent(OrderEvent):
    """Order execution (fill) event from broker."""

    event_type: Literal[EventType.ORDER_FILL] = EventType.ORDER_FILL
    fill_price: float
    fill_quantity: float


class OrderCancelEvent(BaseEvent):
    """Order cancellation event."""

    event_type: Literal[EventType.ORDER_CANCEL] = EventType.ORDER_CANCEL
    order_id: str
    symbol: str
    broker: str
    reason: str


class ErrorEvent(BaseEvent):
    """Error event emitted by any module."""

    event_type: Literal[EventType.ERROR] = EventType.ERROR
    module: str
    error_type: str
    message: str
    traceback: str | None = None
    severity: Literal["WARNING", "ERROR", "CRITICAL"]


class NewsEvent(BaseEvent):
    """Fundamental/news event relevant for strategies."""

    event_type: Literal[EventType.NEWS] = EventType.NEWS
    headline: str
    source_name: str
    symbol: str | None = None
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)


class RegimeChangeEvent(BaseEvent):
    """Market regime transition detected by analytics modules."""

    event_type: Literal[EventType.REGIME_CHANGE] = EventType.REGIME_CHANGE
    previous_regime: str
    new_regime: str
    symbol: str | None = None
    reason: str | None = None


class KillSwitchEvent(BaseEvent):
    """Risk kill switch activation event."""

    event_type: Literal[EventType.KILL_SWITCH] = EventType.KILL_SWITCH
    reason: str
    triggered_by: str


class SystemStartEvent(BaseEvent):
    """System startup lifecycle event."""

    event_type: Literal[EventType.SYSTEM_START] = EventType.SYSTEM_START
    environment: str


class SystemStopEvent(BaseEvent):
    """System shutdown lifecycle event."""

    event_type: Literal[EventType.SYSTEM_STOP] = EventType.SYSTEM_STOP
    reason: str | None = None


class SnapshotEvent(BaseEvent):
    """Snapshot persistence lifecycle event."""

    event_type: Literal[EventType.SNAPSHOT] = EventType.SNAPSHOT
    snapshot_id: str
    path: str


class StrategyStateChangeEvent(BaseEvent):
    """Strategy state transition event emitted by registry."""

    event_type: Literal[EventType.STRATEGY_STATE_CHANGE] = EventType.STRATEGY_STATE_CHANGE
    strategy_id: str
    previous_state: str | None = None
    new_state: str
    reason: str | None = None


EventUnion: TypeAlias = (
    TickEvent
    | BarCloseEvent
    | SignalEvent
    | OrderSubmitEvent
    | OrderFillEvent
    | OrderCancelEvent
    | ErrorEvent
    | NewsEvent
    | RegimeChangeEvent
    | KillSwitchEvent
    | SystemStartEvent
    | SystemStopEvent
    | SnapshotEvent
    | StrategyStateChangeEvent
)
