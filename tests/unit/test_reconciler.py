from __future__ import annotations

from datetime import UTC, datetime

import pytest

from execution.order_models import Account, Order, OrderStatus, Position
from execution.reconciler import Reconciler
from risk.risk_models import OrderSide, OrderType


class _FakeAdapter:
    broker = "paper"

    def __init__(self, positions: list[Position], orders: list[Order], equity: float) -> None:
        self._positions = positions
        self._orders = orders
        self._equity = equity

    async def get_open_positions(self) -> list[Position]:
        return self._positions

    async def list_orders(self) -> list[Order]:
        return self._orders

    async def get_account(self) -> Account:
        return Account(
            account_id="acc",
            broker="paper",
            balance=10000.0,
            unrealized_pnl=self._equity - 10000.0,
            margin_used=0.0,
            currency="USD",
            is_paper=True,
            leverage=100.0,
            updated_at=datetime.now(UTC),
        )


def _position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        broker="paper",
        side=OrderSide.BUY,
        quantity=1.0,
        entry_price=1.1,
        current_price=1.1,
        stop_loss=1.095,
        take_profit=1.105,
        trailing_stop_price=None,
        unrealized_pnl=0.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id=f"sig-{symbol}",
        strategy_id="s",
    )


def _order(order_id: str, broker_order_id: str, status: OrderStatus, account_equity: float | None = None) -> Order:
    metadata = {"account_equity": account_equity} if account_equity is not None else {}
    return Order(
        order_id=order_id,
        broker_order_id=broker_order_id,
        client_order_id=f"cid-{order_id}",
        signal_id=f"sig-{order_id}",
        risk_check_id=f"rc-{order_id}",
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1.0,
        price=1.1,
        stop_loss=1.095,
        take_profit=1.105,
        trailing_stop=None,
        time_in_force="GTC",
        status=status,
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_reconciler_detects_phantom_and_ghost_positions() -> None:
    reconciler = Reconciler()
    adapter = _FakeAdapter(positions=[_position("GBPUSD")], orders=[], equity=10000.0)
    report = await reconciler.reconcile(adapter, internal_positions=[_position("EURUSD")], internal_orders=[])
    assert report.phantom_positions
    assert report.ghost_positions


@pytest.mark.asyncio
async def test_reconciler_detects_missed_fill() -> None:
    reconciler = Reconciler()
    broker_order = _order("o1", "b1", OrderStatus.FILLED)
    internal = _order("o1", "b1", OrderStatus.SUBMITTED)
    adapter = _FakeAdapter(positions=[], orders=[broker_order], equity=10000.0)
    report = await reconciler.reconcile(adapter, internal_positions=[], internal_orders=[internal])
    assert report.missed_fills


@pytest.mark.asyncio
async def test_reconciler_equity_mismatch_over_one_percent_is_critical() -> None:
    reconciler = Reconciler()
    internal = _order("o1", "b1", OrderStatus.SUBMITTED, account_equity=10250.0)
    adapter = _FakeAdapter(positions=[], orders=[], equity=10000.0)
    report = await reconciler.reconcile(adapter, internal_positions=[], internal_orders=[internal])
    assert report.equity_mismatch is not None
    assert report.equity_mismatch > 1.0
    assert report.severity == "critical"


@pytest.mark.asyncio
async def test_reconciler_is_clean_when_states_match() -> None:
    reconciler = Reconciler()
    p = _position("EURUSD")
    o = _order("o1", "b1", OrderStatus.SUBMITTED, account_equity=10000.0)
    adapter = _FakeAdapter(positions=[p], orders=[o], equity=10000.0)
    report = await reconciler.reconcile(adapter, internal_positions=[p], internal_orders=[o])
    assert report.is_clean is True
