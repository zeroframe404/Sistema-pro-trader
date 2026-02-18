from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.config_models import BrokerConfig
from core.event_bus import EventBus
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass
from data.connectors.mock_connector import MockConnector
from data.feed_manager import FeedManager
from data.models import OHLCVBar
from data.normalizer import Normalizer


def _make_connector(
    broker_id: str,
    broker_type: str,
    run_id: str,
    bus: EventBus,
    bars: list[OHLCVBar] | None = None,
    error_rate: float = 0.0,
) -> MockConnector:
    cfg = BrokerConfig(
        broker_id=broker_id,
        broker_type=broker_type,
        enabled=True,
        paper_mode=True,
        extra={"error_rate": error_rate, "latency_ms": 1},
    )
    return MockConnector(
        config=cfg,
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.feed"),
        run_id=run_id,
        ohlcv_data={"EURUSD": bars or []},
        error_rate=error_rate,
    )



def _sample_bars() -> list[OHLCVBar]:
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    return [
        OHLCVBar(
            symbol="EURUSD",
            broker="primary",
            timeframe="M1",
            timestamp_open=start,
            timestamp_close=start + timedelta(minutes=1),
            open=1.1,
            high=1.2,
            low=1.0,
            close=1.15,
            volume=10,
            asset_class=AssetClass.FOREX,
            source="mock",
        )
    ]


@pytest.mark.asyncio
async def test_feed_manager_start_connects_connectors(tmp_path: Path) -> None:
    configure_logging(run_id="run-feed", environment="development", log_level="INFO")
    bus = EventBus()
    connector = _make_connector("mock1", "mock", "run-feed", bus)
    manager = FeedManager([connector], bus, "run-feed", tmp_path)

    await manager.start()
    statuses = manager.get_connector_status()

    assert len(statuses) == 1
    assert statuses[0].connected is True
    await manager.stop()


@pytest.mark.asyncio
async def test_health_check_returns_connector_states(tmp_path: Path) -> None:
    configure_logging(run_id="run-feed", environment="development", log_level="INFO")
    bus = EventBus()
    connector = _make_connector("mock1", "mock", "run-feed", bus)
    manager = FeedManager([connector], bus, "run-feed", tmp_path)

    await manager.start()
    health = await manager.health_check()

    assert health["mock1"] is True
    await manager.stop()


@pytest.mark.asyncio
async def test_get_ohlcv_serves_from_cache_after_first_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_logging(run_id="run-feed", environment="development", log_level="INFO")
    bus = EventBus()
    bars = _sample_bars()
    connector = _make_connector("mock1", "primary", "run-feed", bus, bars=bars)
    manager = FeedManager([connector], bus, "run-feed", tmp_path)

    await manager.start()

    calls = {"n": 0}
    original = connector.get_ohlcv

    async def wrapped_get_ohlcv(*args, **kwargs):
        calls["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(connector, "get_ohlcv", wrapped_get_ohlcv)

    start = bars[0].timestamp_open
    end = bars[0].timestamp_open
    first = await manager.get_ohlcv("EURUSD", "M1", start, end, preferred_broker="primary")
    second = await manager.get_ohlcv("EURUSD", "M1", start, end, preferred_broker="primary")

    assert first == bars
    assert second == bars
    assert calls["n"] == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_get_ohlcv_fetches_connector_when_cache_empty(tmp_path: Path) -> None:
    configure_logging(run_id="run-feed", environment="development", log_level="INFO")
    bus = EventBus()
    bars = _sample_bars()
    connector = _make_connector("mock1", "primary", "run-feed", bus, bars=bars)
    manager = FeedManager([connector], bus, "run-feed", tmp_path)

    await manager.start()
    result = await manager.get_ohlcv(
        "EURUSD",
        "M1",
        bars[0].timestamp_open,
        bars[0].timestamp_open,
        preferred_broker="primary",
    )

    assert result == bars
    await manager.stop()


@pytest.mark.asyncio
async def test_fallback_used_when_primary_fails(tmp_path: Path) -> None:
    configure_logging(run_id="run-feed", environment="development", log_level="INFO")
    bus = EventBus()

    primary = _make_connector("primary", "primary", "run-feed", bus, bars=[], error_rate=1.0)
    backup_bar = _sample_bars()[0].model_copy(update={"broker": "backup"})
    backup = _make_connector("backup", "backup", "run-feed", bus, bars=[backup_bar], error_rate=0.0)

    manager = FeedManager([primary, backup], bus, "run-feed", tmp_path)
    await manager.start()

    result = await manager.get_ohlcv(
        "EURUSD",
        "M1",
        backup_bar.timestamp_open,
        backup_bar.timestamp_open,
        preferred_broker="primary",
    )

    assert result == [backup_bar]
    await manager.stop()
