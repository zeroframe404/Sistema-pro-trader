"""Asynchronous event bus with asyncio backend and Redis-compatible adapter."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from core.event_types import EventType
from core.events import BaseEvent

EventHandler = Callable[[BaseEvent], Awaitable[Any]]
EventFilter = dict[str, Any] | Callable[[BaseEvent], bool] | None


@dataclass(slots=True)
class EventBusMetrics:
    """Runtime metrics exposed by the event bus."""

    backend: str
    events_published: int
    events_processed: int
    queue_size: int
    subscribers: int
    redis_connected: bool = False


@dataclass(slots=True)
class _Subscriber:
    """Internal subscriber registration."""

    handler: EventHandler
    filter_spec: EventFilter = None


class _EventBusBackend(Protocol):
    """Protocol implemented by concrete event bus backends."""

    def subscribe(self, event_type: EventType, handler: EventHandler, filter_spec: EventFilter) -> None:
        ...

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        ...

    async def publish(self, event: BaseEvent) -> None:
        ...

    def publish_nowait(self, event: BaseEvent) -> None:
        ...

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    def get_metrics(self) -> EventBusMetrics:
        ...


class AsyncioBackend:
    """In-process event bus backend powered by asyncio.Queue."""

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[_Subscriber]] = {}
        self._queue: asyncio.Queue[BaseEvent] = asyncio.Queue()
        self._events_published = 0
        self._events_processed = 0
        self._running = False
        self._worker_task: asyncio.Task[None] | None = None
        self._logger = logging.getLogger(__name__)

    def subscribe(self, event_type: EventType, handler: EventHandler, filter_spec: EventFilter) -> None:
        bucket = self._subscribers.setdefault(event_type, [])
        bucket.append(_Subscriber(handler=handler, filter_spec=filter_spec))

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        bucket = self._subscribers.get(event_type, [])
        self._subscribers[event_type] = [item for item in bucket if item.handler is not handler]

    async def publish(self, event: BaseEvent) -> None:
        self._events_published += 1
        await self._queue.put(event)

    def publish_nowait(self, event: BaseEvent) -> None:
        self._events_published += 1
        self._queue.put_nowait(event)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker(), name="event-bus-worker")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    def get_metrics(self) -> EventBusMetrics:
        return EventBusMetrics(
            backend="asyncio",
            events_published=self._events_published,
            events_processed=self._events_processed,
            queue_size=self._queue.qsize(),
            subscribers=sum(len(items) for items in self._subscribers.values()),
            redis_connected=False,
        )

    async def _worker(self) -> None:
        while self._running:
            event = await self._queue.get()
            try:
                subscribers = self._matching_subscribers(event)
                if subscribers:
                    await asyncio.gather(*(self._dispatch(item, event) for item in subscribers))
            finally:
                self._queue.task_done()

    async def _dispatch(self, subscriber: _Subscriber, event: BaseEvent) -> None:
        try:
            if self._passes_filter(subscriber.filter_spec, event):
                await subscriber.handler(event)
        except Exception:  # noqa: BLE001
            self._logger.exception("Event handler failed", extra={"event_type": event.event_type})
        finally:
            self._events_processed += 1

    def _matching_subscribers(self, event: BaseEvent) -> list[_Subscriber]:
        exact = self._subscribers.get(event.event_type, [])
        wildcard = self._subscribers.get(EventType.ALL, [])
        return [*exact, *wildcard]

    @staticmethod
    def _passes_filter(filter_spec: EventFilter, event: BaseEvent) -> bool:
        if filter_spec is None:
            return True
        if callable(filter_spec):
            return bool(filter_spec(event))
        for key, expected in filter_spec.items():
            if not hasattr(event, key):
                return False
            if getattr(event, key) != expected:
                return False
        return True


class RedisBackend:
    """Redis-compatible adapter that gracefully degrades to asyncio backend."""

    def __init__(self, redis_url: str | None, fallback: AsyncioBackend) -> None:
        self._redis_url = redis_url
        self._fallback = fallback
        self._logger = logging.getLogger(__name__)
        self._redis_connected = False

    def subscribe(self, event_type: EventType, handler: EventHandler, filter_spec: EventFilter) -> None:
        self._fallback.subscribe(event_type, handler, filter_spec)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._fallback.unsubscribe(event_type, handler)

    async def publish(self, event: BaseEvent) -> None:
        await self._fallback.publish(event)

    def publish_nowait(self, event: BaseEvent) -> None:
        self._fallback.publish_nowait(event)

    async def start(self) -> None:
        self._redis_connected = await self._probe_redis()
        if not self._redis_connected:
            self._logger.warning("Redis unavailable, falling back to asyncio backend")
        else:
            self._logger.info("Redis probe succeeded; using asyncio compatibility mode")
        await self._fallback.start()

    async def stop(self) -> None:
        await self._fallback.stop()

    def get_metrics(self) -> EventBusMetrics:
        metrics = self._fallback.get_metrics()
        metrics.backend = "redis"
        metrics.redis_connected = self._redis_connected
        return metrics

    async def _probe_redis(self) -> bool:
        if not self._redis_url:
            return False
        try:
            import redis.asyncio as redis_async
        except Exception:  # noqa: BLE001
            return False

        client = redis_async.from_url(self._redis_url)
        try:
            await asyncio.wait_for(client.ping(), timeout=1.0)
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            await client.aclose()


class EventBus:
    """Public event bus API used by all modules."""

    def __init__(self, backend: str = "asyncio", redis_url: str | None = None) -> None:
        asyncio_backend = AsyncioBackend()
        if backend == "redis":
            self._backend: _EventBusBackend = RedisBackend(redis_url=redis_url, fallback=asyncio_backend)
        else:
            self._backend = asyncio_backend

    def subscribe(
        self,
        event_type: EventType,
        handler: EventHandler | None = None,
        *,
        filter: EventFilter = None,
    ) -> Callable[[EventHandler], EventHandler] | EventHandler:
        """Register an async handler for an event type.

        Supports direct calls and decorator style usage.
        """

        if handler is None:

            def decorator(func: EventHandler) -> EventHandler:
                self._validate_handler(func)
                self._backend.subscribe(event_type, func, filter)
                return func

            return decorator

        self._validate_handler(handler)
        self._backend.subscribe(event_type, handler, filter)
        return handler

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a registered handler from an event type bucket."""

        self._backend.unsubscribe(event_type, handler)

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event asynchronously."""

        await self._backend.publish(event)

    def publish_nowait(self, event: BaseEvent) -> None:
        """Publish an event without awaiting queue insertion."""

        self._backend.publish_nowait(event)

    async def start(self) -> None:
        """Start event bus lifecycle."""

        await self._backend.start()

    async def stop(self) -> None:
        """Stop event bus lifecycle."""

        await self._backend.stop()

    def get_metrics(self) -> EventBusMetrics:
        """Return runtime event bus metrics."""

        return self._backend.get_metrics()

    @staticmethod
    def _validate_handler(handler: EventHandler) -> None:
        if not inspect.iscoroutinefunction(handler):
            raise TypeError("Event handlers must be async functions")
