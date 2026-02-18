from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from execution.order_models import Fill, Order, Position
from risk.risk_models import OrderSide, OrderType


def test_order_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Order(
            client_order_id="cid",
            signal_id="sig",
            risk_check_id="rc",
            symbol="EURUSD",
            broker="paper",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.0,
            time_in_force="GTC",
        )


def test_fill_json_roundtrip() -> None:
    fill = Fill(
        order_id="o-1",
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=1.0,
        price=1.1,
        commission=0.5,
        timestamp=datetime.now(UTC),
        is_partial=False,
        is_paper=True,
    )
    restored = Fill.model_validate_json(fill.model_dump_json())
    assert restored.order_id == "o-1"
    assert restored.price == 1.1


def test_position_unrealized_pnl_buy_positive_price_move() -> None:
    position = Position(
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=1.0,
        entry_price=1.1000,
        current_price=1.1050,
        stop_loss=1.0950,
        take_profit=1.1100,
        trailing_stop_price=None,
        unrealized_pnl=500.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id="sig",
        strategy_id="s",
    )
    assert position.unrealized_pnl == 500.0


def test_client_order_id_is_explicit_and_stable() -> None:
    order = Order(
        client_order_id="fixed-id",
        signal_id="sig",
        risk_check_id="rc",
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1.0,
        time_in_force="GTC",
    )
    assert order.client_order_id == "fixed-id"
