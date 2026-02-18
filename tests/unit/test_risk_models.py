from __future__ import annotations

from datetime import UTC, datetime

import pytest

from execution.order_models import Account, Position
from risk.risk_models import (
    OrderSide,
    PositionSize,
    PositionSizingMethod,
    RiskCheck,
    RiskCheckStatus,
)


def test_risk_check_approved_serialization_roundtrip() -> None:
    check = RiskCheck(
        signal_id="sig-1",
        symbol="EURUSD",
        broker="mock_dev",
        status=RiskCheckStatus.APPROVED,
        approved_size=0.2,
        approved_side=OrderSide.BUY,
        suggested_sl=1.095,
        suggested_tp=1.105,
        risk_amount=100.0,
        risk_percent=1.0,
        reward_risk_ratio=2.0,
        portfolio_snapshot={"equity": 10000.0},
    )
    restored = RiskCheck.model_validate_json(check.model_dump_json())
    assert restored.status == RiskCheckStatus.APPROVED
    assert restored.approved_side == OrderSide.BUY
    assert restored.portfolio_snapshot["equity"] == 10000.0


def test_position_size_requires_cap_reason_when_capped() -> None:
    with pytest.raises(ValueError):
        PositionSize(
            method=PositionSizingMethod.PERCENT_RISK,
            units=1.0,
            notional_value=1000.0,
            risk_amount=100.0,
            risk_percent=0.01,
            max_allowed_units=1.0,
            was_capped=True,
            cap_reason=None,
        )


def test_position_r_multiple_with_stop_loss() -> None:
    position = Position(
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=1.0,
        entry_price=1.1000,
        current_price=1.1030,
        stop_loss=1.0980,
        take_profit=1.1060,
        trailing_stop_price=None,
        unrealized_pnl=300.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id="sig",
        strategy_id="s",
    )
    assert position.r_multiple == pytest.approx(1.5, rel=1e-6)


def test_position_pnl_pct_for_buy_and_sell() -> None:
    buy = Position(
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=1.0,
        entry_price=1.1000,
        current_price=1.1110,
        stop_loss=1.0950,
        take_profit=1.1200,
        trailing_stop_price=None,
        unrealized_pnl=0.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id="sig",
        strategy_id="s",
    )
    sell = buy.model_copy(update={"side": OrderSide.SELL, "current_price": 1.0890})
    assert buy.pnl_pct == pytest.approx(1.0, rel=1e-6)
    assert sell.pnl_pct == pytest.approx(1.0, rel=1e-6)


def test_account_equity_is_balance_plus_unrealized() -> None:
    account = Account(
        account_id="acc-1",
        broker="paper",
        balance=10000.0,
        unrealized_pnl=250.0,
        margin_used=1000.0,
        currency="USD",
        is_paper=True,
        leverage=100.0,
        updated_at=datetime.now(UTC),
    )
    assert account.equity == 10250.0
    assert account.margin_free == 9250.0
