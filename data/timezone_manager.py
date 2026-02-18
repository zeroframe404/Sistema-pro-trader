"""Timezone conversion and market session helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from data.asset_types import AssetClass


class TimezoneManager:
    """Manage broker timezone conversion and market session checks."""

    BROKER_TIMEZONES = {
        "mt5": "Etc/GMT+2",
        "iqoption": "UTC",
        "iol": "America/Argentina/Buenos_Aires",
        "fxpro": "Etc/GMT+2",
        "ccxt": "UTC",
        "mock": "UTC",
    }

    def to_utc(self, dt: datetime, broker: str) -> datetime:
        """Convert broker-local datetime to UTC."""

        tz_name = self.BROKER_TIMEZONES.get(broker.lower(), "UTC")
        tz = ZoneInfo(tz_name)

        if dt.tzinfo is None:
            local_dt = dt.replace(tzinfo=tz)
        else:
            local_dt = dt.astimezone(tz)

        return local_dt.astimezone(UTC)

    def from_utc(self, dt: datetime, target_tz: str) -> datetime:
        """Convert UTC datetime to a target timezone."""

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(ZoneInfo(target_tz))

    def is_market_open(self, symbol: str, asset_class: AssetClass, dt: datetime) -> bool:
        """Return whether the market is open for the asset class at datetime dt."""

        dt_utc = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        dt_utc = dt_utc.astimezone(UTC)

        if asset_class == AssetClass.CRYPTO:
            return True

        if asset_class in {AssetClass.FOREX, AssetClass.CFD, AssetClass.COMMODITY, AssetClass.INDEX}:
            ny_time = dt_utc.astimezone(ZoneInfo("America/New_York"))
            weekday = ny_time.weekday()  # Monday=0

            if weekday in {0, 1, 2, 3}:
                return True
            if weekday == 4:
                return ny_time.hour < 17
            if weekday == 5:
                return False
            return ny_time.hour >= 17

        if asset_class in {
            AssetClass.STOCK,
            AssetClass.CEDEAR,
            AssetClass.BOND,
            AssetClass.TREASURY,
            AssetClass.OBLIGATION,
            AssetClass.MUTUAL_FUND,
            AssetClass.CAUTION,
            AssetClass.AUCTION,
            AssetClass.ETF,
        }:
            # Generic weekday exchange window in UTC for module-level checks.
            if dt_utc.weekday() >= 5:
                return False
            return 11 <= dt_utc.hour < 22

        return True

    def get_next_open(self, symbol: str, asset_class: AssetClass, from_dt: datetime) -> datetime:
        """Return the next market open datetime in UTC."""

        current = from_dt if from_dt.tzinfo is not None else from_dt.replace(tzinfo=UTC)
        current = current.astimezone(UTC)

        for _ in range(24 * 8):
            if self.is_market_open(symbol=symbol, asset_class=asset_class, dt=current):
                return current
            current += timedelta(hours=1)

        return current

    def get_trading_sessions(self, dt: datetime) -> list[str]:
        """Return active major trading sessions at given datetime."""

        dt_utc = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        dt_utc = dt_utc.astimezone(UTC)

        sessions: list[str] = []
        hour = dt_utc.hour

        if 7 <= hour < 16:
            sessions.append("london")
        if 12 <= hour < 21:
            sessions.append("newyork")
        if "london" in sessions and "newyork" in sessions:
            sessions.append("overlap")

        return sessions
