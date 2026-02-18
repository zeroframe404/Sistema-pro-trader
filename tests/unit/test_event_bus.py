from __future__ import annotations

import asyncio

import pytest

from core.event_bus import EventBus
from core.event_types import EventType
from core.events import SignalEvent, TickEvent


@pytest.mark.asyncio
async def test_subscriber_receives_event() -> None:
    bus = EventBus()
    await bus.start()

    received: list[TickEvent] = []
    done = asyncio.Event()

    async def handler(event: TickEvent) -> None:
        received.append(event)
        done.set()

    bus.subscribe(EventType.TICK, handler)

    event = TickEvent(
        source="test",
        run_id="run-1",
        symbol="EURUSD",
        broker="paper",
        bid=1.1,
        ask=1.2,
        last=1.15,
        volume=100,
    )
    await bus.publish(event)

    await asyncio.wait_for(done.wait(), timeout=1.0)
    await bus.stop()

    assert len(received) == 1
    assert received[0].symbol == "EURUSD"


@pytest.mark.asyncio
async def test_filter_by_symbol() -> None:
    bus = EventBus()
    await bus.start()

    symbols: list[str] = []
    done = asyncio.Event()

    async def handler(event: TickEvent) -> None:
        symbols.append(event.symbol)
        done.set()

    bus.subscribe(EventType.TICK, handler, filter={"symbol": "EURUSD"})

    await bus.publish(
        TickEvent(
            source="test",
            run_id="run-1",
            symbol="BTCUSD",
            broker="paper",
            bid=10,
            ask=11,
            last=10.5,
            volume=1,
        )
    )
    await bus.publish(
        TickEvent(
            source="test",
            run_id="run-1",
            symbol="EURUSD",
            broker="paper",
            bid=1.1,
            ask=1.2,
            last=1.15,
            volume=100,
        )
    )

    await asyncio.wait_for(done.wait(), timeout=1.0)
    await bus.stop()

    assert symbols == ["EURUSD"]


@pytest.mark.asyncio
async def test_multiple_subscribers_receive_same_event() -> None:
    bus = EventBus()
    await bus.start()

    first = asyncio.Event()
    second = asyncio.Event()

    async def h1(_: TickEvent) -> None:
        first.set()

    async def h2(_: TickEvent) -> None:
        second.set()

    bus.subscribe(EventType.TICK, h1)
    bus.subscribe(EventType.TICK, h2)

    await bus.publish(
        TickEvent(
            source="test",
            run_id="run-1",
            symbol="EURUSD",
            broker="paper",
            bid=1,
            ask=2,
            last=1.5,
            volume=10,
        )
    )

    await asyncio.wait_for(first.wait(), timeout=1.0)
    await asyncio.wait_for(second.wait(), timeout=1.0)
    await bus.stop()


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    await bus.start()

    calls = 0

    async def handler(_: TickEvent) -> None:
        nonlocal calls
        calls += 1

    bus.subscribe(EventType.TICK, handler)
    bus.unsubscribe(EventType.TICK, handler)

    await bus.publish(
        TickEvent(
            source="test",
            run_id="run-1",
            symbol="EURUSD",
            broker="paper",
            bid=1,
            ask=2,
            last=1.5,
            volume=10,
        )
    )

    await asyncio.sleep(0.1)
    await bus.stop()
    assert calls == 0


@pytest.mark.asyncio
async def test_subscriber_to_all_receives_all_types() -> None:
    bus = EventBus()
    await bus.start()

    received: list[EventType] = []
    done = asyncio.Event()

    async def handler(event: TickEvent | SignalEvent) -> None:
        received.append(event.event_type)
        if len(received) == 2:
            done.set()

    bus.subscribe(EventType.ALL, handler)

    await bus.publish(
        TickEvent(
            source="test",
            run_id="run-1",
            symbol="EURUSD",
            broker="paper",
            bid=1,
            ask=2,
            last=1.5,
            volume=10,
        )
    )
    await bus.publish(
        SignalEvent(
            source="test",
            run_id="run-1",
            symbol="EURUSD",
            broker="paper",
            strategy_id="s1",
            strategy_version="1.0.0",
            direction="BUY",
            confidence=0.8,
            reasons=[{"factor": "test"}],
            timeframe="M5",
            horizon="1h",
        )
    )

    await asyncio.wait_for(done.wait(), timeout=1.0)
    await bus.stop()

    assert received == [EventType.TICK, EventType.SIGNAL]


@pytest.mark.asyncio
async def test_bus_start_stop_cleanly() -> None:
    bus = EventBus()
    await bus.start()
    await bus.stop()
    metrics = bus.get_metrics()
    assert metrics.events_published == 0
    assert metrics.queue_size == 0
