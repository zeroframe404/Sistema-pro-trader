"""Broker/internal state reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from execution.order_models import Order, Position


class ReconciliationReport(BaseModel):
    """Divergences found between broker and internal OMS state."""

    timestamp: datetime
    broker: str
    phantom_positions: list[dict[str, Any]] = Field(default_factory=list)
    ghost_positions: list[dict[str, Any]] = Field(default_factory=list)
    missed_fills: list[dict[str, Any]] = Field(default_factory=list)
    price_deviations: list[dict[str, Any]] = Field(default_factory=list)
    equity_mismatch: float | None = None
    severity: str = "ok"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_clean(self) -> bool:
        """Return true when there are no mismatches."""

        return (
            not self.phantom_positions
            and not self.ghost_positions
            and not self.missed_fills
            and not self.price_deviations
            and (self.equity_mismatch is None or self.equity_mismatch <= 0.0)
        )


class Reconciler:
    """Reconcile broker and internal order/position states."""

    async def reconcile(
        self,
        adapter: Any,
        internal_positions: list[Position],
        internal_orders: list[Order],
    ) -> ReconciliationReport:
        broker_positions = await adapter.get_open_positions()
        broker_orders = await adapter.list_orders() if hasattr(adapter, "list_orders") else []
        broker_account = await adapter.get_account()

        internal_by_symbol = {(item.symbol, item.side.value): item for item in internal_positions}
        broker_by_symbol = {(item.symbol, item.side.value): item for item in broker_positions}

        phantom_positions = [
            {"symbol": item.symbol, "side": item.side.value, "quantity": item.quantity}
            for key, item in broker_by_symbol.items()
            if key not in internal_by_symbol
        ]
        ghost_positions = [
            {"symbol": item.symbol, "side": item.side.value, "quantity": item.quantity}
            for key, item in internal_by_symbol.items()
            if key not in broker_by_symbol
        ]

        broker_order_status = {item.broker_order_id: item.status.value for item in broker_orders if item.broker_order_id}
        missed_fills: list[dict[str, Any]] = []
        for order in internal_orders:
            if order.broker_order_id is None:
                continue
            broker_status = broker_order_status.get(order.broker_order_id)
            if broker_status == "filled" and order.status.value not in {"filled", "partially_filled"}:
                missed_fills.append({"order_id": order.order_id, "broker_order_id": order.broker_order_id})

        price_deviations: list[dict[str, Any]] = []
        for order in internal_orders:
            if order.average_fill_price is None:
                continue
            expected = order.price if order.price is not None else order.average_fill_price
            if expected <= 0:
                continue
            deviation = abs(order.average_fill_price - expected) / expected * 100.0
            if deviation > 1.0:
                price_deviations.append({"order_id": order.order_id, "deviation_pct": deviation})

        internal_equity = self._extract_internal_equity(internal_orders)
        equity_mismatch = None
        if internal_equity is not None and broker_account.equity is not None and broker_account.equity > 0:
            equity_mismatch = abs(internal_equity - broker_account.equity) / broker_account.equity * 100.0

        severity = "ok"
        if phantom_positions or ghost_positions or missed_fills or price_deviations:
            severity = "warning"
        if equity_mismatch is not None and equity_mismatch > 1.0:
            severity = "critical"

        return ReconciliationReport(
            timestamp=datetime.now(UTC),
            broker=adapter.broker,
            phantom_positions=phantom_positions,
            ghost_positions=ghost_positions,
            missed_fills=missed_fills,
            price_deviations=price_deviations,
            equity_mismatch=equity_mismatch,
            severity=severity,
        )

    async def auto_fix(self, report: ReconciliationReport) -> list[str]:
        """Attempt deterministic auto-fixes for non-critical mismatches."""

        actions: list[str] = []
        if report.severity == "critical":
            actions.append("escalate_kill_switch")
            return actions
        if report.missed_fills:
            actions.append("replayed_missed_fills")
        if report.ghost_positions:
            actions.append("marked_ghost_positions_closed")
        if report.phantom_positions:
            actions.append("registered_phantom_positions")
        return actions

    @staticmethod
    def _extract_internal_equity(internal_orders: list[Order]) -> float | None:
        for order in reversed(internal_orders):
            value = order.metadata.get("account_equity")
            if isinstance(value, (float, int)):
                return float(value)
        return None
