"""SQLite storage for metadata and quality artifacts."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from data.asset_types import AssetClass
from data.models import AssetInfo, DataQualityReport, Tick


class SQLiteStore:
    """Async SQLite store for asset metadata, quality reports, and tick cache."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    symbol TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (symbol, broker)
                );

                CREATE TABLE IF NOT EXISTS quality_reports (
                    symbol TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS last_prices (
                    symbol TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (symbol, broker)
                );
                """
            )
            await db.commit()

    async def save_asset_info(self, asset: AssetInfo) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO assets (symbol, broker, payload)
                VALUES (?, ?, ?)
                """,
                (asset.symbol, asset.broker, asset.model_dump_json()),
            )
            await db.commit()

    async def get_asset_info(self, symbol: str, broker: str) -> AssetInfo | None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT payload FROM assets WHERE symbol = ? AND broker = ?",
                (symbol, broker),
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return AssetInfo.model_validate_json(row[0])

    async def list_assets(
        self,
        broker: str | None = None,
        asset_class: AssetClass | None = None,
    ) -> list[AssetInfo]:
        query = "SELECT payload FROM assets"
        params: list[str] = []
        conditions: list[str] = []

        if broker is not None:
            conditions.append("broker = ?")
            params.append(broker)

        if conditions:
            query = f"{query} WHERE {' AND '.join(conditions)}"

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

        assets = [AssetInfo.model_validate_json(row[0]) for row in rows]
        if asset_class is not None:
            assets = [item for item in assets if item.asset_class == asset_class]

        return assets

    async def save_quality_report(self, report: DataQualityReport) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO quality_reports (symbol, broker, timeframe, created_at, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    report.symbol,
                    report.broker,
                    report.timeframe,
                    report.period_end.isoformat(),
                    report.model_dump_json(),
                ),
            )
            await db.commit()

    async def get_latest_quality_report(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
    ) -> DataQualityReport | None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT payload
                FROM quality_reports
                WHERE symbol = ? AND broker = ? AND timeframe = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (symbol, broker, timeframe),
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return DataQualityReport.model_validate_json(row[0])

    async def update_last_price(self, tick: Tick) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO last_prices (symbol, broker, payload)
                VALUES (?, ?, ?)
                """,
                (tick.symbol, tick.broker, tick.model_dump_json()),
            )
            await db.commit()

    async def get_last_price(self, symbol: str, broker: str) -> Tick | None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT payload FROM last_prices WHERE symbol = ? AND broker = ?",
                (symbol, broker),
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return Tick.model_validate_json(row[0])
