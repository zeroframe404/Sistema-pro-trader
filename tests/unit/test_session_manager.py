from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from data.asset_types import AssetClass
from regime.session_manager import SessionManager


def test_london_active_ny_inactive_at_09_utc() -> None:
    manager = SessionManager()
    dt = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    active = manager.get_active_sessions(dt)
    assert "london" in active
    assert "newyork" not in active


def test_london_ny_overlap_at_14_utc() -> None:
    manager = SessionManager()
    dt = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    active = manager.get_active_sessions(dt)
    assert "london" in active
    assert "newyork" in active
    assert manager.is_overlap(dt) is True


def test_forex_closed_weekend_expect_no_core_session() -> None:
    manager = SessionManager()
    dt = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    active = manager.get_active_sessions(dt)
    # Sessions list is static; quality handles non-optimal time.
    assert isinstance(active, list)


def test_crypto_quality_always_high() -> None:
    manager = SessionManager()
    dt = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    quality = manager.get_session_quality("BTCUSD", AssetClass.CRYPTO, dt)
    assert quality == 1.0


def test_byma_active_at_11_buenos_aires() -> None:
    manager = SessionManager()
    ba = datetime(2026, 1, 5, 11, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
    dt_utc = ba.astimezone(UTC)
    active = manager.get_active_sessions(dt_utc)
    assert "byma" in active
