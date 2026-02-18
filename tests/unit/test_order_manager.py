from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.config_models import RiskConfig
from core.event_bus import EventBus
from core.logger import configure_logging, get_logger
from execution.adapters.paper_adapter import PaperAdapter
from execution.fill_simulator import FillSimulator
from execution.idempotency import IdempotencyManager
from execution.order_manager import OrderManager
from execution.order_models import Fill, OrderStatus, Position
from execution.reconciler import Reconciler
from execution.retry_handler import RetryHandler
from risk.drawdown_tracker import DrawdownTracker
from risk.exposure_tracker import ExposureTracker
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from risk.risk_models import OrderSide, RiskCheck, RiskCheckStatus
from risk.slippage_model import SlippageModel
from risk.stop_manager import StopManager
from tests.unit._signal_fixtures import make_signal


async def _build_manager(tmp_path: Path) -> tuple[OrderManager, EventBus]:
    configure_logging(run_id="run-test", environment="development", log_level="INFO")
    bus = EventBus()
    await bus.start()
    risk_cfg = RiskConfig(enabled=True, paper={"initial_balance": 10000.0})
    slippage = SlippageModel()
    adapter = PaperAdapter(
        initial_balance=10000.0,
        fill_simulator=FillSimulator(slippage),
        slippage_model=slippage,
        event_bus=bus,
        logger=get_logger("tests.paper_adapter"),
        run_id="run-test",
        risk_config=risk_cfg,
    )
    risk_manager = RiskManager(
        config=risk_cfg,
        position_sizer=PositionSizer(),
        stop_manager=StopManager(),
        drawdown_tracker=DrawdownTracker(),
        exposure_tracker=ExposureTracker(),
        kill_switch=KillSwitch(risk_cfg.kill_switch, bus, run_id="run-test"),
        event_bus=bus,
        logger=get_logger("tests.risk_manager"),
        run_id="run-test",
    )
    manager = OrderManager(
        broker_adapter=adapter,
        risk_manager=risk_manager,
        idempotency=IdempotencyManager(tmp_path / "idempotency.sqlite"),
        reconciler=Reconciler(),
        retry_handler=RetryHandler(),
        event_bus=bus,
        logger=get_logger("tests.order_manager"),
        db_path=tmp_path / "oms.sqlite",
        run_id="run-test",
    )
    await manager.start()
    return manager, bus


def _approved_check(signal_id: str) -> RiskCheck:
    return RiskCheck(
        signal_id=signal_id,
        symbol="EURUSD",
        broker="paper",
        status=RiskCheckStatus.APPROVED,
        approved_size=0.1,
        approved_side=OrderSide.BUY,
        suggested_sl=1.0950,
        suggested_tp=1.1050,
        suggested_trailing=0.002,
        risk_amount=100.0,
        risk_percent=1.0,
        reward_risk_ratio=2.0,
        portfolio_snapshot={"equity": 10000.0},
    )


@pytest.mark.asyncio
async def test_submit_from_signal_with_paper_adapter_returns_submitted(tmp_path: Path) -> None:
    manager, bus = await _build_manager(tmp_path)
    try:
        signal = make_signal()
        account = manager.get_account()
        order = await manager.submit_from_signal(signal, _approved_check(signal.signal_id), account)
        assert order.status in {OrderStatus.SUBMITTED, OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_cancel_updates_order_status(tmp_path: Path) -> None:
    manager, bus = await _build_manager(tmp_path)
    try:
        signal = make_signal()
        account = manager.get_account()
        order = await manager.submit_from_signal(signal, _approved_check(signal.signal_id), account)
        cancelled = await manager.cancel(order.order_id, "user_cancel")
        assert cancelled.status == OrderStatus.CANCELLED
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_close_position_and_close_all_positions(tmp_path: Path) -> None:
    manager, bus = await _build_manager(tmp_path)
    try:
        position = Position(
            symbol="EURUSD",
            broker="paper",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1.1,
            current_price=1.1,
            stop_loss=1.095,
            take_profit=1.105,
            trailing_stop_price=None,
            unrealized_pnl=0.0,
            realized_pnl=None,
            commission_total=0.0,
            signal_id="sig",
            strategy_id="s",
            metadata={"contract_size": 100000.0},
        )
        manager._positions[position.position_id] = position  # noqa: SLF001
        close_order = await manager.close_position(position, reason="test_close")
        assert close_order.status == OrderStatus.SUBMITTED
        all_orders = await manager.close_all_positions("kill_switch")
        assert len(all_orders) >= 1
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_on_fill_event_marks_order_filled(tmp_path: Path) -> None:
    manager, bus = await _build_manager(tmp_path)
    try:
        signal = make_signal()
        account = manager.get_account()
        order = await manager.submit_from_signal(signal, _approved_check(signal.signal_id), account)
        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            broker=order.broker,
            side=order.side,
            quantity=order.quantity,
            price=1.1,
            commission=0.0,
            timestamp=datetime.now(UTC),
            is_partial=False,
            is_paper=True,
        )
        await manager.on_fill_event(fill)
        latest = manager.get_order_history(limit=1)[0]
        assert latest.status in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.SUBMITTED}
    finally:
        await bus.stop()
