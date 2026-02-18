from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.config_models import BrokerConfig, SignalsConfig
from core.event_bus import EventBus
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass
from data.connectors.mock_connector import MockConnector
from data.feed_manager import FeedManager
from data.models import OHLCVBar
from data.normalizer import Normalizer
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from signals.signal_engine import SignalEngine


def _generate_bars(symbol: str, timeframe: str, total: int = 900) -> list[OHLCVBar]:
    start = datetime.now(UTC) - timedelta(hours=total)
    bars: list[OHLCVBar] = []
    price = 1.05
    for idx in range(total):
        drift = 0.0002 if idx % 7 else -0.0001
        open_price = price
        close = max(0.0001, open_price + drift)
        high = max(open_price, close) + 0.0004
        low = min(open_price, close) - 0.0004
        ts_open = start + timedelta(hours=idx)
        bars.append(
            OHLCVBar(
                symbol=symbol,
                broker="mock_dev",
                timeframe=timeframe,
                timestamp_open=ts_open,
                timestamp_close=ts_open + timedelta(hours=1),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000 + idx,
                spread=0.0001,
                source="test",
                asset_class=AssetClass.FOREX,
            )
        )
        price = close
    return bars


async def _build_engine(tmp_path: Path) -> tuple[SignalEngine, FeedManager, EventBus]:
    configure_logging(run_id="run-test", environment="development", log_level="INFO")
    event_bus = EventBus()
    await event_bus.start()

    connector = MockConnector(
        config=BrokerConfig(
            broker_id="mock_dev",
            broker_type="mock",
            enabled=True,
            paper_mode=True,
            extra={},
        ),
        event_bus=event_bus,
        normalizer=Normalizer(),
        logger=get_logger("tests.mock_connector"),
        run_id="run-test",
        ohlcv_data={"EURUSD": _generate_bars("EURUSD", "H1")},
        latency_ms=0.0,
        error_rate=0.0,
    )
    feed_manager = FeedManager(
        connectors=[connector],
        event_bus=event_bus,
        run_id="run-test",
        data_store_path=tmp_path / "data_store",
        logger=get_logger("tests.feed_manager"),
    )
    await feed_manager.start()

    indicator_engine = IndicatorEngine(data_repository=feed_manager.get_repository())
    regime_detector = RegimeDetector(
        indicator_engine=indicator_engine,
        data_repository=feed_manager.get_repository(),
        event_bus=event_bus,
        run_id="run-test",
    )

    signal_engine = SignalEngine(
        config=SignalsConfig(),
        indicator_engine=indicator_engine,
        regime_detector=regime_detector,
        data_repository=feed_manager.get_repository(),
        event_bus=event_bus,
        logger=get_logger("tests.signal_engine"),
        run_id="run-test",
    )
    await signal_engine.start()
    return signal_engine, feed_manager, event_bus


@pytest.mark.asyncio
async def test_signal_pipeline_end_to_end(tmp_path: Path) -> None:
    signal_engine, feed_manager, event_bus = await _build_engine(tmp_path)
    try:
        decision = await signal_engine.analyze(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            horizon="2 horas",
        )
        assert decision.display_decision in {"COMPRAR", "VENDER", "NO HAY INFO CLARA", "NO OPERAR"}
        assert 0 <= decision.confidence_percent <= 100
        assert decision.ensemble.explanation or decision.ensemble.short_explanation
        assert decision.top_reasons is not None
        if decision.top_reasons:
            weight_sum = sum(item.weight for item in decision.top_reasons)
            assert 0.7 <= weight_sum <= 1.01
    finally:
        await feed_manager.stop()
        await event_bus.stop()


@pytest.mark.asyncio
async def test_anti_overtrading_blocks_second_immediate_signal(tmp_path: Path) -> None:
    signal_engine, feed_manager, event_bus = await _build_engine(tmp_path)
    try:
        first = await signal_engine.analyze("EURUSD", "mock_dev", "H1", "2 horas")
        second = await signal_engine.analyze("EURUSD", "mock_dev", "H1", "2 horas")
        assert first.display_decision in {"COMPRAR", "VENDER", "NO HAY INFO CLARA", "NO OPERAR"}
        assert second.display_decision == "NO OPERAR"
    finally:
        await feed_manager.stop()
        await event_bus.stop()


@pytest.mark.asyncio
async def test_analyze_multi_timeframe_returns_all_requested(tmp_path: Path) -> None:
    signal_engine, feed_manager, event_bus = await _build_engine(tmp_path)
    try:
        result = await signal_engine.analyze_multi_timeframe(
            symbol="EURUSD",
            broker="mock_dev",
            timeframes=["M15", "H1", "H4", "D1"],
            horizon="1 dia",
        )
        assert set(result) == {"M15", "H1", "H4", "D1"}
    finally:
        await feed_manager.stop()
        await event_bus.stop()


@pytest.mark.asyncio
async def test_pipeline_latency_under_500ms(tmp_path: Path) -> None:
    signal_engine, feed_manager, event_bus = await _build_engine(tmp_path)
    try:
        start = time.perf_counter()
        await signal_engine.analyze("EURUSD", "mock_dev", "H1", "2 horas")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500
    finally:
        await feed_manager.stop()
        await event_bus.stop()
