"""Multi-level cache manager (L1 memory + optional L2 Redis)."""

from __future__ import annotations

import fnmatch
import json
from datetime import UTC, datetime
from typing import Any, cast

from cachetools import TTLCache

from data.models import OHLCVBar, Tick


class CacheManager:
    """Cache manager with in-memory LRU/TTL and optional Redis backend."""

    def __init__(self, l1_max_size: int = 1000, redis_client: Any = None) -> None:
        self._ohlcv_l1: TTLCache[str, list[OHLCVBar]] = TTLCache(maxsize=l1_max_size, ttl=300)
        self._tick_l1: TTLCache[str, Tick] = TTLCache(maxsize=l1_max_size, ttl=60)
        self._redis = redis_client

    async def get_ohlcv(self, key: str) -> list[OHLCVBar] | None:
        if key in self._ohlcv_l1:
            return cast(list[OHLCVBar], self._ohlcv_l1[key])

        if self._redis is None:
            return None

        raw = await self._redis.get(f"ohlcv:{key}")
        if not raw:
            return None

        payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        decoded = json.loads(payload)
        bars = [OHLCVBar.model_validate(item) for item in cast(list[dict[str, Any]], decoded)]
        self._ohlcv_l1[key] = bars
        return bars

    async def set_ohlcv(self, key: str, bars: list[OHLCVBar], ttl_seconds: int = 300) -> None:
        self._ohlcv_l1[key] = bars
        if self._redis is None:
            return

        payload = json.dumps([bar.model_dump(mode="json") for bar in bars], default=str)
        await self._redis.setex(f"ohlcv:{key}", ttl_seconds, payload)

    async def get_tick(self, symbol: str, broker: str) -> Tick | None:
        key = f"{broker}:{symbol}"
        if key in self._tick_l1:
            return cast(Tick, self._tick_l1[key])

        if self._redis is None:
            return None

        raw = await self._redis.get(f"tick:{key}")
        if not raw:
            return None

        payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        tick = Tick.model_validate(json.loads(payload))
        self._tick_l1[key] = tick
        return tick

    async def set_tick(self, tick: Tick) -> None:
        key = f"{tick.broker}:{tick.symbol}"
        self._tick_l1[key] = tick

        if self._redis is None:
            return

        payload = json.dumps(tick.model_dump(mode="json"), default=str)
        await self._redis.setex(f"tick:{key}", 60, payload)

    async def invalidate(self, pattern: str) -> None:
        ohlcv_keys = [key for key in self._ohlcv_l1.keys() if fnmatch.fnmatch(key, pattern)]
        for key in ohlcv_keys:
            self._ohlcv_l1.pop(key, None)

        tick_keys = [key for key in self._tick_l1.keys() if fnmatch.fnmatch(key, pattern)]
        for key in tick_keys:
            self._tick_l1.pop(key, None)

        if self._redis is None:
            return

        async for key in self._redis.scan_iter(match=f"*{pattern}*"):
            await self._redis.delete(key)

    def make_ohlcv_key(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> str:
        start_utc = start.astimezone(UTC) if start.tzinfo is not None else start.replace(tzinfo=UTC)
        end_utc = end.astimezone(UTC) if end.tzinfo is not None else end.replace(tzinfo=UTC)
        return f"{broker}:{symbol}:{timeframe}:{start_utc.isoformat()}:{end_utc.isoformat()}"
