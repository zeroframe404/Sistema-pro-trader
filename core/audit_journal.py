"""Audit journal persistence for strategy decision traceability."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import aiofiles  # type: ignore[import-untyped]
from pydantic import BaseModel, Field


class JournalEntry(BaseModel):
    """Audit trail record for one strategy decision."""

    entry_id: str
    timestamp: datetime
    run_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    raw_inputs: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    scores: dict[str, Any] = Field(default_factory=dict)
    decision: str
    confidence: float
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    triggered_rule: str
    triggered_condition: str


DateRange = tuple[datetime, datetime] | None


class JournalStorage(Protocol):
    """Storage backend contract for journal entries."""

    async def write(self, entry: JournalEntry) -> None:
        ...

    async def query(
        self,
        strategy_id: str | None,
        symbol: str | None,
        date_range: DateRange,
    ) -> list[JournalEntry]:
        ...


class JSONLStorage:
    """Append-only JSONL storage backend."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def write(self, entry: JournalEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self._path, mode="a", encoding="utf-8") as stream:
            await stream.write(entry.model_dump_json())
            await stream.write("\n")

    async def query(
        self,
        strategy_id: str | None,
        symbol: str | None,
        date_range: DateRange,
    ) -> list[JournalEntry]:
        if not self._path.exists():
            return []

        entries: list[JournalEntry] = []
        async with aiofiles.open(self._path, encoding="utf-8") as stream:
            async for raw_line in stream:
                line = raw_line.strip()
                if not line:
                    continue
                entry = JournalEntry.model_validate_json(line)
                if _match_entry(entry, strategy_id, symbol, date_range):
                    entries.append(entry)

        return entries


class SQLiteStorage:
    """SQLite storage backend for indexed audit queries."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    async def write(self, entry: JournalEntry) -> None:
        await asyncio.to_thread(self._write_sync, entry)

    async def query(
        self,
        strategy_id: str | None,
        symbol: str | None,
        date_range: DateRange,
    ) -> list[JournalEntry]:
        return await asyncio.to_thread(self._query_sync, strategy_id, symbol, date_range)

    def _initialize_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS journal (
                    entry_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    raw_inputs TEXT NOT NULL,
                    features TEXT NOT NULL,
                    scores TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasons TEXT NOT NULL,
                    triggered_rule TEXT NOT NULL,
                    triggered_condition TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _write_sync(self, entry: JournalEntry) -> None:
        payload = _entry_to_sql_row(entry)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO journal (
                    entry_id, timestamp, run_id, strategy_id, strategy_version, symbol,
                    timeframe, raw_inputs, features, scores, decision, confidence,
                    reasons, triggered_rule, triggered_condition
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            conn.commit()

    def _query_sync(
        self,
        strategy_id: str | None,
        symbol: str | None,
        date_range: DateRange,
    ) -> list[JournalEntry]:
        sql = "SELECT * FROM journal"
        clauses: list[str] = []
        params: list[Any] = []

        if strategy_id:
            clauses.append("strategy_id = ?")
            params.append(strategy_id)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if date_range:
            clauses.append("timestamp BETWEEN ? AND ?")
            params.append(date_range[0].isoformat())
            params.append(date_range[1].isoformat())

        if clauses:
            sql = f"{sql} WHERE {' AND '.join(clauses)}"

        sql = f"{sql} ORDER BY timestamp"

        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(sql, params).fetchall()

        entries: list[JournalEntry] = []
        for row in rows:
            entries.append(
                JournalEntry(
                    entry_id=row[0],
                    timestamp=row[1],
                    run_id=row[2],
                    strategy_id=row[3],
                    strategy_version=row[4],
                    symbol=row[5],
                    timeframe=row[6],
                    raw_inputs=json.loads(row[7]),
                    features=json.loads(row[8]),
                    scores=json.loads(row[9]),
                    decision=row[10],
                    confidence=row[11],
                    reasons=json.loads(row[12]),
                    triggered_rule=row[13],
                    triggered_condition=row[14],
                )
            )
        return entries


class AuditJournal:
    """Audit journal facade with JSONL default and optional SQLite backend."""

    def __init__(
        self,
        jsonl_path: Path,
        *,
        enable_sqlite: bool = False,
        sqlite_path: Path | None = None,
    ) -> None:
        self._jsonl_storage = JSONLStorage(jsonl_path)
        self._sqlite_storage: SQLiteStorage | None = None

        if enable_sqlite:
            resolved_sqlite = sqlite_path or jsonl_path.with_suffix(".db")
            self._sqlite_storage = SQLiteStorage(resolved_sqlite)

    async def write(self, entry: JournalEntry) -> None:
        """Write one journal entry to configured storage backends."""

        tasks = [self._jsonl_storage.write(entry)]
        if self._sqlite_storage is not None:
            tasks.append(self._sqlite_storage.write(entry))
        await asyncio.gather(*tasks)

    async def query(
        self,
        strategy_id: str | None = None,
        symbol: str | None = None,
        date_range: DateRange = None,
    ) -> list[JournalEntry]:
        """Query journal entries from SQLite when enabled, otherwise JSONL."""

        if self._sqlite_storage is not None:
            return await self._sqlite_storage.query(strategy_id, symbol, date_range)
        return await self._jsonl_storage.query(strategy_id, symbol, date_range)


def _entry_to_sql_row(entry: JournalEntry) -> tuple[Any, ...]:
    return (
        entry.entry_id,
        entry.timestamp.isoformat(),
        entry.run_id,
        entry.strategy_id,
        entry.strategy_version,
        entry.symbol,
        entry.timeframe,
        json.dumps(entry.raw_inputs, sort_keys=True),
        json.dumps(entry.features, sort_keys=True),
        json.dumps(entry.scores, sort_keys=True),
        entry.decision,
        entry.confidence,
        json.dumps(entry.reasons, sort_keys=True),
        entry.triggered_rule,
        entry.triggered_condition,
    )


def _match_entry(
    entry: JournalEntry,
    strategy_id: str | None,
    symbol: str | None,
    date_range: DateRange,
) -> bool:
    if strategy_id and entry.strategy_id != strategy_id:
        return False
    if symbol and entry.symbol != symbol:
        return False
    if date_range:
        start, end = date_range
        if entry.timestamp < start or entry.timestamp > end:
            return False
    return True
