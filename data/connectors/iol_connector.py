"""InvertirOnline connector wrapper."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from data.base_connector import DataConnector
from data.models import AssetInfo, OHLCVBar, Tick


class IOLConnector(DataConnector):
    """IOL REST connector with OAuth2 placeholders."""

    _available = True
    BASE_URL = "https://api.invertironline.com"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client = httpx.AsyncClient(timeout=10.0)
        self._token: str | None = None

    @retry(wait=wait_exponential(min=1, max=60), stop=stop_after_attempt(5), reraise=True)
    async def connect(self) -> bool:
        username = str(self.config.extra.get("username", ""))
        password = str(self.config.extra.get("password", ""))
        if not username or not password:
            self._record_error("IOL credentials missing")
            self._mark_connected(False)
            return False

        response = await self._client.post(
            f"{self.BASE_URL}/token",
            data={"grant_type": "password", "username": username, "password": password},
        )
        if response.status_code >= 400:
            self._record_error(f"IOL auth failed: {response.status_code}")
            self._mark_connected(False)
            return False

        payload = response.json()
        self._token = str(payload.get("access_token", ""))
        self._mark_connected(bool(self._token))
        return self.is_connected()

    async def disconnect(self) -> None:
        await self._client.aclose()
        self._mark_connected(False)

    async def ping(self) -> float:
        if not self.is_connected():
            raise RuntimeError("IOL connector not connected")
        start = datetime.now(UTC)
        _ = await self._client.get(f"{self.BASE_URL}/api/v2/Cuenta/EstadoDeCuenta")
        latency = (datetime.now(UTC) - start).total_seconds() * 1000
        self._record_ping(latency)
        return latency

    async def get_available_symbols(self) -> list[AssetInfo]:
        return []

    async def get_asset_info(self, symbol: str) -> AssetInfo | None:
        _ = symbol
        return None

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[OHLCVBar]:
        _ = (symbol, timeframe, start, end, limit)
        return []

    async def subscribe_ticks(self, symbol: str, callback: Callable[[Tick], Awaitable[None]]) -> None:
        _ = callback
        self._track_subscription(symbol, True)

    async def unsubscribe_ticks(self, symbol: str) -> None:
        self._track_subscription(symbol, False)

    async def get_cedear_ratio(self, symbol: str) -> float | None:
        _ = symbol
        return None

    async def get_cauciones(self) -> list[dict[str, Any]]:
        return []

    async def get_fci_list(self) -> list[AssetInfo]:
        return []
