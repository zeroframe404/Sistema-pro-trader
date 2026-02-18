"""Shared live-adapter fallback implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from execution.adapters.base_broker_adapter import BaseBrokerAdapter
from execution.order_models import Account, Fill, Order, OrderStatus, Position


class LiveAdapterStub(BaseBrokerAdapter):
    """Minimal but functional live adapter wrapper with availability gates."""

    broker = "live_stub"
    is_paper = False
    _available = False

    def __init__(self, broker: str, available: bool, run_id: str = "unknown") -> None:
        self.broker = broker
        self._available = available
        self._connected = available
        self._run_id = run_id
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._fill_callbacks: list = []
        self._account = Account(
            account_id=f"{broker}-{run_id}",
            broker=broker,
            balance=0.0,
            currency="USD",
            is_paper=False,
            leverage=1.0,
            margin_used=0.0,
            unrealized_pnl=0.0,
        )

    async def get_account(self) -> Account:
        return self._account

    async def get_open_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def get_order_status(self, broker_order_id: str) -> Order:
        if broker_order_id not in self._orders:
            raise KeyError(f"order not found: {broker_order_id}")
        return self._orders[broker_order_id]

    async def submit_order(self, order: Order) -> str:
        if not self._available:
            raise RuntimeError(f"{self.broker} adapter unavailable")
        broker_order_id = str(uuid4())
        self._orders[broker_order_id] = order.model_copy(
            update={
                "broker_order_id": broker_order_id,
                "status": OrderStatus.SUBMITTED,
                "submitted_at": datetime.now(UTC),
                "is_paper": False,
            }
        )
        return broker_order_id

    async def cancel_order(self, broker_order_id: str) -> bool:
        order = self._orders.get(broker_order_id)
        if order is None:
            return False
        self._orders[broker_order_id] = order.model_copy(update={"status": OrderStatus.CANCELLED})
        return True

    async def modify_order(self, broker_order_id: str, new_sl: float | None, new_tp: float | None) -> bool:
        order = self._orders.get(broker_order_id)
        if order is None:
            return False
        self._orders[broker_order_id] = order.model_copy(update={"stop_loss": new_sl, "take_profit": new_tp})
        return True

    async def close_position(self, position: Position, partial_pct: float = 1.0) -> str:
        _ = (position, partial_pct)
        if not self._available:
            raise RuntimeError(f"{self.broker} adapter unavailable")
        return str(uuid4())

    async def subscribe_fills(self, callback: Callable[[Fill], Awaitable[None]]) -> None:
        self._fill_callbacks.append(callback)

    async def ping(self) -> float:
        return 50.0 if self._available else 9999.0

    def is_connected(self) -> bool:
        return self._connected and self._available

    async def list_orders(self) -> list[Order]:
        return list(self._orders.values())

    async def emit_fill(self, fill: Fill) -> None:
        """Utility for tests to simulate broker fill callback."""

        for callback in self._fill_callbacks:
            await callback(fill)
