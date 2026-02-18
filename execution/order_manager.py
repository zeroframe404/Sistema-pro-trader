"""Order lifecycle manager for OMS."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from structlog.stdlib import BoundLogger

from core.event_bus import EventBus
from core.events import OrderCancelEvent, OrderSubmitEvent
from core.logger import get_logger
from execution.adapters.base_broker_adapter import BaseBrokerAdapter
from execution.idempotency import IdempotencyManager
from execution.order_models import Account, Fill, Order, OrderStatus, Position, PositionStatus
from execution.reconciler import Reconciler
from execution.retry_handler import RetryHandler
from risk.risk_manager import RiskManager
from risk.risk_models import OrderSide, OrderType, RiskCheck, RiskCheckStatus
from signals.signal_models import Signal, SignalDirection


class OrderManager:
    """Manage order submission, updates, fills, and position state."""

    def __init__(
        self,
        broker_adapter: BaseBrokerAdapter,
        risk_manager: RiskManager,
        idempotency: IdempotencyManager,
        reconciler: Reconciler,
        retry_handler: RetryHandler,
        event_bus: EventBus,
        logger: BoundLogger | None = None,
        db_path: Path = Path("data_store/oms.sqlite"),
        run_id: str = "unknown",
    ) -> None:
        self._adapter = broker_adapter
        self._risk_manager = risk_manager
        self._idempotency = idempotency
        self._reconciler = reconciler
        self._retry = retry_handler
        self._event_bus = event_bus
        self._logger = logger or get_logger("execution.order_manager")
        self._run_id = run_id

        self._orders: dict[str, Order] = {}
        self._orders_by_broker_id: dict[str, str] = {}
        self._positions: dict[str, Position] = {}
        self._history: list[Order] = []
        self._account: Account | None = None
        self._lock = asyncio.Lock()

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    async def start(self) -> None:
        """Initialize account snapshot and fill subscription."""

        self._account = await self._adapter.get_account()
        await self._adapter.subscribe_fills(self.on_fill_event)

    async def submit_from_signal(
        self,
        signal: Signal,
        risk_check: RiskCheck,
        account: Account,
    ) -> Order:
        """Submit an order from validated signal and risk decision."""

        self._account = account
        if risk_check.status == RiskCheckStatus.REJECTED or (risk_check.approved_size or 0.0) <= 0:
            rejected = self._build_order(signal, risk_check, status=OrderStatus.REJECTED)
            rejected.reject_reason = ";".join(risk_check.rejection_reasons or ["risk_rejected"])
            async with self._lock:
                self._register_order(rejected)
            await self._persist_order(rejected)
            return rejected

        client_order_id = self._idempotency.generate_client_order_id(signal)
        order = self._build_order(signal, risk_check, status=OrderStatus.PENDING, client_order_id=client_order_id)

        is_duplicate, existing = await self._idempotency.check_and_register(client_order_id, order)
        if is_duplicate and existing is not None:
            return existing

        async with self._lock:
            self._register_order(order)
        broker_order_id = await self._retry.run(lambda: self._adapter.submit_order(order))
        current_order = self._orders.get(order.order_id, order)
        current_status = current_order.status
        final_status = (
            current_status
            if current_status in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}
            else OrderStatus.SUBMITTED
        )
        submitted = current_order.model_copy(
            update={
                "broker_order_id": broker_order_id,
                "status": final_status,
                "submitted_at": current_order.submitted_at or datetime.now(UTC),
            }
        )
        await self._idempotency.mark_as_submitted(client_order_id, broker_order_id)
        async with self._lock:
            self._register_order(submitted)
        await self._persist_order(submitted)

        await self._event_bus.publish(
            OrderSubmitEvent(
                source="execution.order_manager",
                run_id=self._run_id,
                order_id=submitted.order_id,
                client_order_id=submitted.client_order_id,
                risk_check_id=submitted.risk_check_id,
                symbol=submitted.symbol,
                broker=submitted.broker,
                direction=submitted.side.value,
                order_type=submitted.order_type.value,
                quantity=submitted.quantity,
                price=submitted.price,
                stop_loss=submitted.stop_loss,
                take_profit=submitted.take_profit,
                status=submitted.status.value,
                is_paper=submitted.is_paper,
                metadata=submitted.metadata,
            )
        )
        return submitted

    async def cancel(self, order_id: str, reason: str) -> Order:
        """Cancel pending/submitted order."""

        order = self._orders[order_id]
        if order.broker_order_id is not None:
            await self._adapter.cancel_order(order.broker_order_id)
        cancelled = order.model_copy(update={"status": OrderStatus.CANCELLED, "cancelled_at": datetime.now(UTC)})
        self._register_order(cancelled)
        await self._persist_order(cancelled)
        await self._event_bus.publish(
            OrderCancelEvent(
                source="execution.order_manager",
                run_id=self._run_id,
                order_id=cancelled.order_id,
                symbol=cancelled.symbol,
                broker=cancelled.broker,
                reason=reason,
            )
        )
        return cancelled

    async def modify(
        self,
        order_id: str,
        new_sl: float | None = None,
        new_tp: float | None = None,
        new_trailing: float | None = None,
    ) -> Order:
        """Modify stop/take-profit/trailing values for an order."""

        order = self._orders[order_id]
        if order.broker_order_id is not None:
            await self._adapter.modify_order(order.broker_order_id, new_sl, new_tp)
        updated = order.model_copy(update={"stop_loss": new_sl, "take_profit": new_tp, "trailing_stop": new_trailing})
        self._register_order(updated)
        await self._persist_order(updated)
        return updated

    async def close_position(self, position: Position, reason: str, partial_pct: float = 1.0) -> Order:
        """Submit a close order for an open position."""

        broker_order_id = await self._adapter.close_position(position, partial_pct=partial_pct)
        close_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
        close_order = Order(
            client_order_id=f"close-{position.position_id}-{int(datetime.now(UTC).timestamp())}",
            signal_id=position.signal_id,
            risk_check_id="close_position",
            symbol=position.symbol,
            broker=position.broker,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=max(position.quantity * partial_pct, 0.0000001),
            price=position.current_price,
            stop_loss=None,
            take_profit=None,
            trailing_stop=None,
            time_in_force="IOC",
            status=OrderStatus.SUBMITTED,
            submitted_at=datetime.now(UTC),
            is_paper=self._adapter.is_paper,
            broker_order_id=broker_order_id,
            metadata={"close_position_id": position.position_id, "reason": reason, **position.metadata},
        )
        self._register_order(close_order)
        await self._persist_order(close_order)
        return close_order

    async def close_all_positions(self, reason: str) -> list[Order]:
        """Close all currently open positions."""

        results: list[Order] = []
        for position in self.get_open_positions():
            results.append(await self.close_position(position, reason=reason))
        return results

    async def on_fill_event(self, fill: Fill) -> None:
        """Handle fill callback from adapter."""

        async with self._lock:
            order = self._orders.get(fill.order_id)
            if order is None:
                broker_lookup = self._orders_by_broker_id.get(fill.order_id)
                if broker_lookup is None:
                    return
                order = self._orders[broker_lookup]

            total_qty = order.filled_quantity + fill.quantity
            avg_price = (
                ((order.average_fill_price or 0.0) * order.filled_quantity + fill.price * fill.quantity)
                / max(total_qty, 1e-12)
            )
            status = OrderStatus.PARTIALLY_FILLED if total_qty < order.quantity else OrderStatus.FILLED
            updated_order = order.model_copy(
                update={
                    "filled_quantity": total_qty,
                    "average_fill_price": avg_price,
                    "commission": order.commission + fill.commission,
                    "filled_at": fill.timestamp,
                    "status": status,
                }
            )
            self._register_order(updated_order)
            await self._persist_order(updated_order)
            await self._persist_fill(fill)

            close_position_id = str(updated_order.metadata.get("close_position_id", ""))
            if close_position_id:
                await self._apply_close_fill(close_position_id, fill)
            else:
                await self._apply_open_fill(updated_order, fill)

            await self._risk_manager.update_on_fill(fill)
            await self._idempotency.mark_as_filled(updated_order.client_order_id, fill)

    async def sync_with_broker(self) -> dict[str, Any]:
        """Reconcile internal OMS state against adapter state."""

        report = await self._reconciler.reconcile(
            adapter=self._adapter,
            internal_positions=list(self._positions.values()),
            internal_orders=list(self._orders.values()),
        )
        fixes = await self._reconciler.auto_fix(report)
        return {"report": report.model_dump(mode="python"), "fixes": fixes}

    def get_open_positions(self) -> list[Position]:
        """Return open positions."""

        return [item for item in self._positions.values() if item.status != PositionStatus.CLOSED]

    def get_order_history(self, limit: int = 100) -> list[Order]:
        """Return latest order history."""

        return self._history[-limit:]

    def get_account(self) -> Account:
        """Return current account snapshot."""

        if self._account is None:
            raise RuntimeError("order manager not started")
        return self._account

    def _build_order(
        self,
        signal: Signal,
        risk_check: RiskCheck,
        *,
        status: OrderStatus,
        client_order_id: str | None = None,
    ) -> Order:
        side = risk_check.approved_side
        if side is None:
            side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL
        order_type_raw = signal.metadata.get("order_type", "MARKET")
        order_type = OrderType(str(order_type_raw))
        return Order(
            client_order_id=client_order_id or f"rejected-{signal.signal_id[:18]}",
            signal_id=signal.signal_id,
            risk_check_id=risk_check.check_id,
            symbol=signal.symbol,
            broker=signal.broker,
            side=side,
            order_type=order_type,
            quantity=max(float(risk_check.approved_size or 0.0), 0.0000001),
            price=signal.entry_price,
            stop_loss=risk_check.suggested_sl,
            take_profit=risk_check.suggested_tp,
            trailing_stop=risk_check.suggested_trailing,
            time_in_force=str(signal.metadata.get("time_in_force", "GTC")),
            status=status,
            is_paper=self._adapter.is_paper,
            metadata={
                "strategy_id": signal.strategy_id,
                "asset_class": str(signal.metadata.get("asset_class", "unknown")),
                "contract_size": float(signal.metadata.get("contract_size", 1.0)),
                "pip_size": float(signal.metadata.get("pip_size", 0.0001)),
                "account_equity": float(signal.metadata.get("account_equity", 0.0)),
            },
        )

    def _register_order(self, order: Order) -> None:
        self._orders[order.order_id] = order
        if order.broker_order_id:
            self._orders_by_broker_id[order.broker_order_id] = order.order_id
        self._history.append(order)

    async def _apply_open_fill(self, order: Order, fill: Fill) -> None:
        position = Position(
            symbol=order.symbol,
            broker=order.broker,
            side=order.side,
            quantity=fill.quantity,
            entry_price=fill.price,
            current_price=fill.price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            trailing_stop_price=None,
            status=PositionStatus.OPEN,
            opened_at=fill.timestamp,
            unrealized_pnl=0.0,
            realized_pnl=None,
            commission_total=fill.commission,
            signal_id=order.signal_id,
            strategy_id=str(order.metadata.get("strategy_id", "signal_ensemble")),
            asset_class=order.metadata.get("asset_class", "unknown"),
            is_paper=order.is_paper,
            metadata=order.metadata,
        )
        self._positions[position.position_id] = position
        await self._persist_position(position)

    async def _apply_close_fill(self, position_id: str, fill: Fill) -> None:
        position = self._positions.get(position_id)
        if position is None:
            return
        close_qty = min(position.quantity, fill.quantity)
        contract_size = float(position.metadata.get("contract_size", 1.0))
        pnl_per_unit = (fill.price - position.entry_price) if position.side == OrderSide.BUY else (position.entry_price - fill.price)
        realized = pnl_per_unit * close_qty * contract_size - fill.commission
        position.quantity -= close_qty
        position.realized_pnl = (position.realized_pnl or 0.0) + realized
        if position.quantity <= 1e-12:
            position.quantity = 0.0
            position.status = PositionStatus.CLOSED
            position.closed_at = fill.timestamp
            position.close_price = fill.price
        await self._risk_manager.update_on_close(position, realized)
        await self._persist_position(position)

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    broker_order_id TEXT,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fills (
                    fill_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    position_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.commit()

    async def _persist_order(self, order: Order) -> None:
        await asyncio.to_thread(self._persist_order_sync, order)

    def _persist_order_sync(self, order: Order) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orders(order_id, broker_order_id, status, payload)
                VALUES (?, ?, ?, ?)
                """,
                (order.order_id, order.broker_order_id, order.status.value, order.model_dump_json()),
            )
            conn.commit()

    async def _persist_fill(self, fill: Fill) -> None:
        await asyncio.to_thread(self._persist_fill_sync, fill)

    def _persist_fill_sync(self, fill: Fill) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fills(fill_id, order_id, payload) VALUES (?, ?, ?)",
                (fill.fill_id, fill.order_id, fill.model_dump_json()),
            )
            conn.commit()

    async def _persist_position(self, position: Position) -> None:
        await asyncio.to_thread(self._persist_position_sync, position)

    def _persist_position_sync(self, position: Position) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO positions(position_id, status, payload) VALUES (?, ?, ?)",
                (position.position_id, position.status.value, json.dumps(position.model_dump(mode="json"))),
            )
            conn.commit()
