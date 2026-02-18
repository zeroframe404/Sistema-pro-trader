"""Event type definitions for the system event bus."""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """Event categories emitted and consumed across the platform."""

    ALL = "ALL"
    TICK = "TICK"
    BAR_CLOSE = "BAR_CLOSE"
    SIGNAL = "SIGNAL"
    ORDER_SUBMIT = "ORDER_SUBMIT"
    ORDER_FILL = "ORDER_FILL"
    ORDER_CANCEL = "ORDER_CANCEL"
    ERROR = "ERROR"
    NEWS = "NEWS"
    REGIME_CHANGE = "REGIME_CHANGE"
    KILL_SWITCH = "KILL_SWITCH"
    SYSTEM_START = "SYSTEM_START"
    SYSTEM_STOP = "SYSTEM_STOP"
    SNAPSHOT = "SNAPSHOT"
    STRATEGY_STATE_CHANGE = "STRATEGY_STATE_CHANGE"
