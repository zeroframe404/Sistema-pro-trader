from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backtest.data_injector import DataInjector, WindowedDataRepository
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.event_types import EventType
from core.events import BarCloseEvent, BaseEvent
from data.asset_types import AssetClass


@pytest.mark.asyncio
async def test_inject_bars_order_and_warmup(tmp_path: Path) -> None:
    run_id = "test-injector-order"
    event_bus, repository, *_rest = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path)
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=10)
        bars = generate_synthetic_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            asset_class=AssetClass.FOREX,
        )
        await repository.save_ohlcv(bars)
        windowed = WindowedDataRepository(repository)
        injector = DataInjector(event_bus, windowed, run_id=run_id)

        emitted: list[BarCloseEvent] = []

        async def on_bar_close(event: BaseEvent) -> None:
            if isinstance(event, BarCloseEvent):
                emitted.append(event)

        event_bus.subscribe(EventType.BAR_CLOSE, on_bar_close)
        received_from_generator: list[BarCloseEvent] = []
        async for event in injector.inject_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            warmup_bars=2,
        ):
            received_from_generator.append(event)
        await asyncio.sleep(0.05)
        assert len(received_from_generator) == len(bars) - 2
        assert len(emitted) == len(bars) - 2
        assert all(
            first.timestamp_close <= second.timestamp_close
            for first, second in zip(received_from_generator, received_from_generator[1:], strict=False)
        )
    finally:
        await event_bus.stop()


@pytest.mark.asyncio
async def test_pause_and_resume(tmp_path: Path) -> None:
    run_id = "test-injector-pause"
    event_bus, repository, *_rest = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path)
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=6)
        bars = generate_synthetic_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            asset_class=AssetClass.FOREX,
        )
        await repository.save_ohlcv(bars)
        windowed = WindowedDataRepository(repository)
        injector = DataInjector(event_bus, windowed, speed_multiplier=float("inf"), run_id=run_id)
        injector.pause()
        collected: list[BarCloseEvent] = []

        async def _run_injection() -> None:
            async for event in injector.inject_bars(
                symbol="EURUSD",
                broker="mock_dev",
                timeframe="H1",
                start=start,
                end=end,
                warmup_bars=0,
            ):
                collected.append(event)

        task = asyncio.create_task(_run_injection())
        await asyncio.sleep(0.02)
        assert len(collected) == 0
        injector.resume()
        await asyncio.wait_for(task, timeout=2.0)
        assert len(collected) == len(bars)
    finally:
        await event_bus.stop()


@pytest.mark.asyncio
async def test_no_look_ahead_visible_count(tmp_path: Path) -> None:
    run_id = "test-injector-lookahead"
    event_bus, repository, *_rest = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path)
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=8)
        bars = generate_synthetic_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            asset_class=AssetClass.FOREX,
        )
        await repository.save_ohlcv(bars)
        windowed = WindowedDataRepository(repository)
        injector = DataInjector(event_bus, windowed, run_id=run_id)
        seen_counts: list[int] = []

        async def on_bar(bar) -> None:
            idx = len(seen_counts) + 1
            seen_counts.append(windowed.visible_count("EURUSD", "mock_dev", "H1"))
            assert seen_counts[-1] == idx

        async for _ in injector.inject_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            warmup_bars=0,
            on_bar=on_bar,
        ):
            pass
        assert seen_counts[-1] == len(bars)
    finally:
        await event_bus.stop()
