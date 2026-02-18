"""News window detector for no-trade periods around macro events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from data.asset_types import AssetClass


class EconomicEvent(BaseModel):
    """Macro event definition."""

    event_id: str
    title: str
    country: str
    currency: str
    scheduled_at: datetime
    impact: str
    affected_assets: list[str] = Field(default_factory=list)
    source: str = "manual"
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None

    @field_validator("scheduled_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        return value.astimezone(UTC)


class NewsWindowDetector:
    """Simple detector with local YAML + optional remote extension points."""

    def __init__(self, calendar_path: Path | None = None) -> None:
        self._calendar_path = calendar_path or Path("config/news_events.yaml")
        self._events: list[EconomicEvent] = []

    async def fetch_upcoming_events(self, hours_ahead: int = 24) -> list[EconomicEvent]:
        """Load upcoming events from local file and keep only near-future entries."""

        now = datetime.now(UTC)
        max_dt = now + timedelta(hours=max(1, hours_ahead))
        self._events = self._load_local_events(now=now, max_dt=max_dt)
        return list(self._events)

    def is_in_news_window(
        self,
        symbol: str,
        asset_class: AssetClass,
        now: datetime,
        minutes_before: int = 30,
        minutes_after: int = 15,
    ) -> tuple[bool, EconomicEvent | None]:
        """Check whether symbol is currently blocked by a macro event window."""

        if asset_class == AssetClass.CRYPTO:
            return False, None

        now_utc = now.astimezone(UTC)
        for event in self._events:
            if not self._event_affects_symbol(event, symbol):
                continue
            start = event.scheduled_at - timedelta(minutes=minutes_before)
            end = event.scheduled_at + timedelta(minutes=minutes_after)
            if start <= now_utc <= end:
                return True, event

        return False, None

    def _load_local_events(self, now: datetime, max_dt: datetime) -> list[EconomicEvent]:
        if not self._calendar_path.exists():
            return []

        loaded = yaml.safe_load(self._calendar_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return []

        raw_items = loaded.get("events", [])
        if not isinstance(raw_items, list):
            return []

        events: list[EconomicEvent] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                event = EconomicEvent.model_validate(item)
            except Exception:
                continue
            if now <= event.scheduled_at <= max_dt:
                events.append(event)

        return events

    @staticmethod
    def _event_affects_symbol(event: EconomicEvent, symbol: str) -> bool:
        symbol_u = symbol.upper()
        if not event.affected_assets:
            return event.currency.upper() in symbol_u
        return any(asset.upper() in symbol_u for asset in event.affected_assets)


__all__ = ["EconomicEvent", "NewsWindowDetector"]
