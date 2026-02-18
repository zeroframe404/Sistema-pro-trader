"""Trading session windows and quality scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from data.asset_types import AssetClass


class SessionManager:
    """Session schedule manager for multi-market assets."""

    SESSIONS: dict[str, dict[str, str]] = {
        "sydney": {"open": "22:00", "close": "07:00", "tz": "UTC"},
        "tokyo": {"open": "00:00", "close": "09:00", "tz": "UTC"},
        "london": {"open": "08:00", "close": "17:00", "tz": "UTC"},
        "newyork": {"open": "13:00", "close": "22:00", "tz": "UTC"},
        "byma": {"open": "11:00", "close": "17:00", "tz": "America/Argentina/Buenos_Aires"},
        "crypto": {"open": "00:00", "close": "23:59", "tz": "UTC"},
    }

    def get_active_sessions(self, dt: datetime) -> list[str]:
        """Return active sessions at datetime."""

        active: list[str] = []
        for name, _cfg in self.SESSIONS.items():
            if self._is_session_active(name, dt):
                active.append(name)
        return active

    def is_overlap(self, dt: datetime) -> bool:
        """Return True when London and New York overlap."""

        active = set(self.get_active_sessions(dt))
        return "london" in active and "newyork" in active

    def get_session_quality(self, symbol: str, asset_class: AssetClass, dt: datetime) -> float:
        """Score market session quality between 0 and 1."""

        _ = symbol
        if asset_class == AssetClass.CRYPTO:
            return 1.0

        active = set(self.get_active_sessions(dt))
        if asset_class == AssetClass.FOREX:
            if self.is_overlap(dt):
                return 1.0
            if "london" in active or "newyork" in active:
                return 0.8
            if "tokyo" in active:
                return 0.5
            return 0.1

        if asset_class in {AssetClass.STOCK, AssetClass.CEDEAR}:
            if "newyork" in active or "byma" in active:
                return 0.9
            return 0.2

        return 0.5

    def time_until_session_open(self, session: str, from_dt: datetime) -> timedelta:
        """Return time delta until next session opening."""

        if session not in self.SESSIONS:
            raise KeyError(f"Unknown session: {session}")

        cfg = self.SESSIONS[session]
        zone = ZoneInfo(cfg["tz"])
        local = from_dt.astimezone(zone)
        open_hour, open_minute = [int(x) for x in cfg["open"].split(":")]

        target = local.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)
        if target <= local:
            target = target + timedelta(days=1)
        return target.astimezone(UTC) - from_dt.astimezone(UTC)

    def _is_session_active(self, session: str, dt: datetime) -> bool:
        cfg = self.SESSIONS[session]
        zone = ZoneInfo(cfg["tz"])
        local = dt.astimezone(zone)

        open_hour, open_minute = [int(x) for x in cfg["open"].split(":")]
        close_hour, close_minute = [int(x) for x in cfg["close"].split(":")]

        open_dt = local.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)
        close_dt = local.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)

        if session == "crypto":
            return True

        if close_dt <= open_dt:
            return local >= open_dt or local <= close_dt
        return open_dt <= local <= close_dt


__all__ = ["SessionManager"]
