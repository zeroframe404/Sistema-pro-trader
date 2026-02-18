"""Idempotency management for order submissions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import UTC
from pathlib import Path

from execution.order_models import Fill, Order, OrderStatus
from signals.signal_models import Signal


class IdempotencyManager:
    """Prevent duplicate order submissions for the same signal intent."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    async def check_and_register(self, client_order_id: str, order: Order) -> tuple[bool, Order | None]:
        """Check existing idempotency record and insert/update as needed."""

        return await asyncio.to_thread(self._check_and_register_sync, client_order_id, order)

    def generate_client_order_id(self, signal: Signal) -> str:
        """Generate deterministic hash key for one signal intent."""

        ts = signal.timestamp.astimezone(UTC).replace(second=0, microsecond=0).isoformat()
        raw = f"{signal.signal_id}|{signal.symbol}|{signal.direction.value}|{signal.timeframe}|{ts}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    async def mark_as_submitted(self, client_order_id: str, broker_order_id: str) -> None:
        """Mark idempotency record as submitted."""

        await asyncio.to_thread(
            self._update_status_sync,
            client_order_id,
            OrderStatus.SUBMITTED.value,
            broker_order_id,
            None,
        )

    async def mark_as_filled(self, client_order_id: str, fill: Fill) -> None:
        """Mark idempotency record as filled and attach fill snapshot."""

        await asyncio.to_thread(
            self._update_status_sync,
            client_order_id,
            OrderStatus.FILLED.value,
            fill.broker_fill_id,
            fill.model_dump(mode="json"),
        )

    def _initialize_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency (
                    client_order_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    broker_order_id TEXT,
                    order_json TEXT NOT NULL,
                    last_fill_json TEXT
                )
                """
            )
            conn.commit()

    def _check_and_register_sync(self, client_order_id: str, order: Order) -> tuple[bool, Order | None]:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT status, order_json FROM idempotency WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
            if row is not None:
                status = str(row[0])
                existing_order = Order.model_validate_json(str(row[1]))
                if status in {
                    OrderStatus.SUBMITTED.value,
                    OrderStatus.FILLED.value,
                    OrderStatus.PARTIALLY_FILLED.value,
                    OrderStatus.PENDING.value,
                }:
                    return True, existing_order
                conn.execute(
                    """
                    UPDATE idempotency
                    SET status = ?, broker_order_id = ?, order_json = ?, last_fill_json = NULL
                    WHERE client_order_id = ?
                    """,
                    (order.status.value, order.broker_order_id, order.model_dump_json(), client_order_id),
                )
                conn.commit()
                return False, None

            conn.execute(
                """
                INSERT INTO idempotency(client_order_id, status, broker_order_id, order_json, last_fill_json)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (client_order_id, order.status.value, order.broker_order_id, order.model_dump_json()),
            )
            conn.commit()
            return False, None

    def _update_status_sync(
        self,
        client_order_id: str,
        status: str,
        broker_order_id: str | None,
        fill_payload: dict | None,
    ) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE idempotency
                SET status = ?, broker_order_id = COALESCE(?, broker_order_id), last_fill_json = COALESCE(?, last_fill_json)
                WHERE client_order_id = ?
                """,
                (status, broker_order_id, json.dumps(fill_payload) if fill_payload is not None else None, client_order_id),
            )
            conn.commit()
