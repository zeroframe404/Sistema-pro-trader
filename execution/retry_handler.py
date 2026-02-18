"""Retry helper with async exponential backoff."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class RetryHandler:
    """Execute async operations with bounded retries and backoff."""

    def __init__(self, max_attempts: int = 3, base_delay: float = 0.1, max_delay: float = 2.0) -> None:
        self._max_attempts = max(max_attempts, 1)
        self._base_delay = max(base_delay, 0.0)
        self._max_delay = max(max_delay, self._base_delay)

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Run operation with retry on raised exceptions."""

        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await operation()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self._max_attempts:
                    break
                delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
                jitter = random.uniform(0, delay * 0.1) if delay > 0 else 0.0
                await asyncio.sleep(delay + jitter)
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry handler failed without explicit exception")
