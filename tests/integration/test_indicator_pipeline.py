from __future__ import annotations

import time

import pytest

from core.config_models import BrokerConfig
from core.event_bus import EventBus
from core.logger import configure_logging, get_logger
from data.connectors.mock_connector import MockConnector
from data.feed_manager import FeedManager
from data.normalizer import Normalizer
from indicators.indicator_engine import IndicatorEngine
from tests.unit._indicator_fixtures import make_bars


@pytest.mark.asyncio
async def test_indicator_pipeline_parquet_to_batch(tmp_path) -> None:
    configure_logging(run_id="run-indicator-pipeline", environment="development", log_level="INFO")
    bars = make_bars([1.0 + i * 0.001 for i in range(1000)], timeframe="H1")

    bus = EventBus()
    cfg = BrokerConfig(
        broker_id="mock_pipe",
        broker_type="mock",
        enabled=True,
        paper_mode=True,
        extra={"latency_ms": 1, "error_rate": 0.0},
    )
    connector = MockConnector(
        config=cfg,
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.indicator.pipeline"),
        run_id="run-indicator-pipeline",
        ohlcv_data={"EURUSD": bars},
    )

    manager = FeedManager([connector], bus, "run-indicator-pipeline", tmp_path)
    await manager.start()

    fetched = await manager.get_ohlcv(
        symbol="EURUSD",
        timeframe="H1",
        start=bars[0].timestamp_open,
        end=bars[-1].timestamp_open,
        preferred_broker="mock",
    )
    assert len(fetched) == len(bars)

    engine = IndicatorEngine(data_repository=manager.get_repository())
    specs = [
        {"id": "EMA", "params": {"period": 20}},
        {"id": "EMA", "params": {"period": 50}},
        {"id": "RSI", "params": {"period": 14}},
        {"id": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}},
        {"id": "ATR", "params": {"period": 14}},
        {"id": "BollingerBands", "params": {"period": 20, "std_dev": 2.0}},
        {"id": "ADX", "params": {"period": 14}},
        {"id": "SuperTrend", "params": {"atr_period": 10, "multiplier": 3.0}},
        {"id": "VWAP"},
        {"id": "SupportResistance", "params": {"method": "fractal", "lookback": 100}},
    ]

    start = time.perf_counter()
    results = await engine.compute_batch(specs, fetched)
    elapsed = time.perf_counter() - start

    assert len(results) == 10
    for series in results.values():
        assert len(series.values) == len(fetched)
    assert elapsed < 2.0

    await manager.stop()


@pytest.mark.asyncio
async def test_mock_connector_bar_to_indicator_under_latency_budget(tmp_path) -> None:
    configure_logging(run_id="run-indicator-latency", environment="development", log_level="INFO")
    bars = make_bars([1.0 + i * 0.001 for i in range(600)], timeframe="H1")

    bus = EventBus()
    await bus.start()
    cfg = BrokerConfig(
        broker_id="mock_latency",
        broker_type="mock",
        enabled=True,
        paper_mode=True,
        extra={"latency_ms": 1, "error_rate": 0.0},
    )
    connector = MockConnector(
        config=cfg,
        event_bus=bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.indicator.latency"),
        run_id="run-indicator-latency",
        ohlcv_data={"EURUSD": bars},
    )

    manager = FeedManager([connector], bus, "run-indicator-latency", tmp_path)
    await manager.start()

    engine = IndicatorEngine(data_repository=manager.get_repository())
    event_bar = bars[-1]

    from core.events import BarCloseEvent

    event = BarCloseEvent(
        source="test",
        run_id="run-indicator-latency",
        symbol=event_bar.symbol,
        broker=event_bar.broker,
        timeframe=event_bar.timeframe,
        open=event_bar.open,
        high=event_bar.high,
        low=event_bar.low,
        close=event_bar.close,
        volume=event_bar.volume,
        timestamp_open=event_bar.timestamp_open,
        timestamp_close=event_bar.timestamp_close,
        timestamp=event_bar.timestamp_close,
    )

    start = time.perf_counter()
    values = await engine.compute_for_bar(event, [{"id": "RSI", "params": {"period": 14}}])
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert values
    assert elapsed_ms < 200.0

    await manager.stop()
    await bus.stop()
