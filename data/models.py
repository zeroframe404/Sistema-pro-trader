"""Data-layer domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from data.asset_types import AssetClass, AssetMarket


class OHLCVBar(BaseModel):
    """Normalized OHLCV bar."""

    symbol: str
    broker: str
    timeframe: str
    timestamp_open: datetime
    timestamp_close: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int | None = None
    spread: float | None = None
    asset_class: AssetClass = AssetClass.UNKNOWN
    source: str

    @field_validator("timestamp_open", "timestamp_close")
    @classmethod
    def validate_timestamp_utc(cls, value: datetime) -> datetime:
        """Normalize timestamps to UTC and require timezone awareness."""

        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_ohlcv(self) -> OHLCVBar:
        """Validate OHLCV value coherence."""

        if self.timestamp_close <= self.timestamp_open:
            raise ValueError("timestamp_close must be greater than timestamp_open")

        prices = (self.open, self.high, self.low, self.close)
        if any(price <= 0 for price in prices):
            raise ValueError("all OHLC prices must be > 0")

        if self.high < max(self.open, self.close) or self.high < self.low:
            raise ValueError("high must be >= max(open, close) and >= low")

        if self.low > min(self.open, self.close):
            raise ValueError("low must be <= min(open, close)")

        if self.volume < 0:
            raise ValueError("volume must be >= 0")

        return self


class Tick(BaseModel):
    """Real-time quote tick."""

    symbol: str
    broker: str
    timestamp: datetime
    bid: float
    ask: float
    last: float | None = None
    volume: float | None = None
    spread: float | None = None
    asset_class: AssetClass = AssetClass.UNKNOWN
    source: str

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_utc(cls, value: datetime) -> datetime:
        """Normalize timestamps to UTC and require timezone awareness."""

        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_tick(self) -> Tick:
        """Validate quote consistency and compute derived fields."""

        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("bid and ask must be > 0")

        if self.bid > self.ask:
            raise ValueError("bid cannot be greater than ask")

        if self.last is not None and self.last <= 0:
            raise ValueError("last must be > 0 when present")

        if self.volume is not None and self.volume < 0:
            raise ValueError("volume must be >= 0")

        if self.spread is None:
            self.spread = self.ask - self.bid
        elif self.spread < 0:
            raise ValueError("spread must be >= 0")

        return self


class OrderBook(BaseModel):
    """Level-2 order book snapshot."""

    symbol: str
    broker: str
    timestamp: datetime
    bids: list[tuple[float, float]] = Field(default_factory=list)
    asks: list[tuple[float, float]] = Field(default_factory=list)
    source: str

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class AssetInfo(BaseModel):
    """Asset metadata from a specific broker."""

    symbol: str
    broker: str
    name: str
    asset_class: AssetClass
    market: AssetMarket = AssetMarket.UNKNOWN
    currency: str
    base_currency: str | None = None
    quote_currency: str | None = None
    contract_size: float = 1.0
    min_volume: float = 0.0
    max_volume: float = 0.0
    volume_step: float = 0.0
    pip_size: float = 0.0
    digits: int = 5
    trading_hours: dict[str, list[str]] = Field(default_factory=dict)
    available_timeframes: list[str] = Field(default_factory=list)
    supported_order_types: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class DataQualityReport(BaseModel):
    """Quality report for a bar series."""

    symbol: str
    broker: str
    timeframe: str
    period_start: datetime
    period_end: datetime
    total_bars: int
    missing_bars: int
    duplicate_bars: int
    corrupt_bars: int
    outlier_bars: int
    timezone_issues: int
    gap_details: list[dict[str, Any]] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=1.0)
    is_usable: bool


class ConnectorStatus(BaseModel):
    """Runtime connector status snapshot."""

    connector_id: str
    broker: str
    connected: bool
    last_ping: datetime | None = None
    latency_ms: float | None = None
    error_count: int = 0
    last_error: str | None = None
    subscribed_symbols: list[str] = Field(default_factory=list)
    is_paper: bool


for _model in (OHLCVBar, Tick, OrderBook, AssetInfo, DataQualityReport, ConnectorStatus):
    _model.model_config = {"extra": "forbid"}
