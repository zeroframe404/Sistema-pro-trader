from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from core.config_models import BrokerConfig
from core.event_bus import EventBus
from core.event_types import EventType
from core.events import BarCloseEvent, TickEvent
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass
from data.connectors.mock_connector import MockConnector
from data.fallback_manager import FallbackManager
from data.models import OHLCVBar, Tick
from data.normalizer import Normalizer


def _broker_config(broker_id: str = "mock_dev", error_rate: float = 0.0, latency_ms: float = 0.0) -> BrokerConfig:
    return BrokerConfig(
        broker_id=broker_id,
        broker_type="mock",
        enabled=True,
        paper_mode=True,
        extra={"error_rate": error_rate, "latency_ms": latency_ms},
    )


def _sample_bar() -> OHLCVBar:
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    return OHLCVBar(
        symbol="EURUSD",
        broker="mock",
        timeframe="M1",
        timestamp_open=start,
        timestamp_close=start + timedelta(minutes=1),
        open=1.1,
        high=1.2,
        low=1.0,
        close=1.15,
        volume=100,
        asset_class=AssetClass.FOREX,
        source="mock",
    )


def _sample_tick() -> Tick:
    return Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=datetime.now(UTC),
        bid=1.1,
        ask=1.2,
        last=1.15,
        volume=1,
        spread=0.1,
        asset_class=AssetClass.FOREX,
        source="mock",
    )


@pytest.mark.asyncio
async def test_mock_connector_connect_returns_true() -> None:
    configure_logging(run_id="run-1", environment="development", log_level="INFO")
    bus = EventBus()
    connector = MockConnector(
        config=_broker_config(),
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock"),
        run_id="run-1",
    )

    assert await connector.connect() is True


@pytest.mark.asyncio
async def test_get_ohlcv_returns_injected_data() -> None:
    configure_logging(run_id="run-1", environment="development", log_level="INFO")
    bus = EventBus()
    bar = _sample_bar()
    connector = MockConnector(
        config=_broker_config(),
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock"),
        run_id="run-1",
        ohlcv_data={"EURUSD": [bar]},
    )

    await connector.connect()
    result = await connector.get_ohlcv("EURUSD", "M1", start=bar.timestamp_open)

    assert result == [bar]


@pytest.mark.asyncio
async def test_subscribe_ticks_callback_called_on_inject_tick() -> None:
    configure_logging(run_id="run-1", environment="development", log_level="INFO")
    bus = EventBus()
    await bus.start()
    connector = MockConnector(
        config=_broker_config(),
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock"),
        run_id="run-1",
    )
    await connector.connect()

    called = asyncio.Event()

    async def callback(_tick: Tick) -> None:
        called.set()

    await connector.subscribe_ticks("EURUSD", callback)
    await connector.inject_tick(_sample_tick())

    await asyncio.wait_for(called.wait(), timeout=1)
    await bus.stop()


@pytest.mark.asyncio
async def test_simulates_configurable_latency() -> None:
    configure_logging(run_id="run-1", environment="development", log_level="INFO")
    bus = EventBus()
    connector = MockConnector(
        config=_broker_config(latency_ms=80),
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock"),
        run_id="run-1",
        latency_ms=80,
    )

    start = time.perf_counter()
    await connector.connect()
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms >= 60


@pytest.mark.asyncio
async def test_error_rate_one_raises_on_calls() -> None:
    configure_logging(run_id="run-1", environment="development", log_level="INFO")
    bus = EventBus()
    connector = MockConnector(
        config=_broker_config(error_rate=1.0),
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock"),
        run_id="run-1",
        error_rate=1.0,
    )

    with pytest.raises(RuntimeError):
        await connector.connect()


@pytest.mark.asyncio
async def test_fallback_switches_to_second_connector_on_failure() -> None:
    configure_logging(run_id="run-1", environment="development", log_level="INFO")
    bus = EventBus()
    failing = MockConnector(
        config=_broker_config(broker_id="primary", error_rate=1.0),
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock"),
        run_id="run-1",
        error_rate=1.0,
    )
    backup_bar = _sample_bar()
    backup = MockConnector(
        config=_broker_config(broker_id="backup", error_rate=0.0),
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock"),
        run_id="run-1",
        ohlcv_data={"EURUSD": [backup_bar]},
    )

    manager = FallbackManager([failing, backup])
    manager.set_priority("EURUSD", ["primary", "backup"])

    bars = await manager.get_ohlcv(
        symbol="EURUSD",
        timeframe="M1",
        start=backup_bar.timestamp_open,
    )

    assert bars == [backup_bar]
    assert manager.get_active_source("EURUSD") == "backup"


@pytest.mark.asyncio
async def test_injected_tick_and_bar_are_published_to_event_bus() -> None:
    configure_logging(run_id="run-1", environment="development", log_level="INFO")
    bus = EventBus()
    await bus.start()
    connector = MockConnector(
        config=_broker_config(),
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock"),
        run_id="run-1",
    )
    await connector.connect()

    tick_received = asyncio.Event()
    bar_received = asyncio.Event()

    @bus.subscribe(EventType.TICK)
    async def _on_tick(_event: TickEvent) -> None:
        tick_received.set()

    @bus.subscribe(EventType.BAR_CLOSE)
    async def _on_bar(_event: BarCloseEvent) -> None:
        bar_received.set()

    await connector.inject_tick(_sample_tick())
    await connector.inject_bar(_sample_bar())

    await asyncio.wait_for(tick_received.wait(), timeout=1)
    await asyncio.wait_for(bar_received.wait(), timeout=1)
    await bus.stop()
