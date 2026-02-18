from __future__ import annotations

from pathlib import Path

import pytest

from execution.idempotency import IdempotencyManager
from execution.order_models import Order, OrderStatus
from risk.risk_models import OrderSide, OrderType
from tests.unit._signal_fixtures import make_signal


def _order(client_order_id: str, signal_id: str = "sig-1") -> Order:
    return Order(
        client_order_id=client_order_id,
        signal_id=signal_id,
        risk_check_id="rc-1",
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
        status=OrderStatus.PENDING,
        is_paper=True,
    )


@pytest.mark.asyncio
async def test_duplicate_signal_returns_existing_order(tmp_path: Path) -> None:
    manager = IdempotencyManager(tmp_path / "idempotency.sqlite")
    client_id = "dup-001"
    order = _order(client_id)
    first_dup, first_existing = await manager.check_and_register(client_id, order)
    assert first_dup is False
    assert first_existing is None

    await manager.mark_as_submitted(client_id, "broker-1")
    second_dup, second_existing = await manager.check_and_register(client_id, order)
    assert second_dup is True
    assert second_existing is not None


@pytest.mark.asyncio
async def test_different_signals_not_duplicates(tmp_path: Path) -> None:
    manager = IdempotencyManager(tmp_path / "idempotency.sqlite")
    dup_a, _ = await manager.check_and_register("id-a", _order("id-a", "sig-a"))
    dup_b, _ = await manager.check_and_register("id-b", _order("id-b", "sig-b"))
    assert dup_a is False
    assert dup_b is False


@pytest.mark.asyncio
async def test_rejected_order_can_be_resubmitted(tmp_path: Path) -> None:
    manager = IdempotencyManager(tmp_path / "idempotency.sqlite")
    client_id = "retry-1"
    rejected = _order(client_id).model_copy(update={"status": OrderStatus.REJECTED})
    await manager.check_and_register(client_id, rejected)
    dup, existing = await manager.check_and_register(client_id, _order(client_id))
    assert dup is False
    assert existing is None


def test_generate_client_order_id_is_deterministic(tmp_path: Path) -> None:
    manager = IdempotencyManager(tmp_path / "idempotency.sqlite")
    signal = make_signal()
    first = manager.generate_client_order_id(signal)
    second = manager.generate_client_order_id(signal)
    assert first == second
