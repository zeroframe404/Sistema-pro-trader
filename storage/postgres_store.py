"""PostgreSQL store contract stub for future production implementation."""

from __future__ import annotations

from datetime import datetime

from data.models import AssetInfo, OHLCVBar


class PostgresStore:
    """Interface-compatible PostgreSQL storage stub."""

    async def initialize(self) -> None:
        """Initialize schema and migrations."""

        raise NotImplementedError("PostgresStore is not implemented in module 1")

    async def save_bars(self, bars: list[OHLCVBar]) -> None:
        """Save OHLCV bars."""

        raise NotImplementedError("PostgresStore is not implemented in module 1")

    async def load_bars(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Load OHLCV bars by range."""

        _ = (symbol, broker, timeframe, start, end)
        raise NotImplementedError("PostgresStore is not implemented in module 1")

    async def save_asset_info(self, asset: AssetInfo) -> None:
        """Save asset metadata."""

        _ = asset
        raise NotImplementedError("PostgresStore is not implemented in module 1")

    async def get_asset_info(self, symbol: str, broker: str) -> AssetInfo | None:
        """Load one asset metadata row."""

        _ = (symbol, broker)
        raise NotImplementedError("PostgresStore is not implemented in module 1")
