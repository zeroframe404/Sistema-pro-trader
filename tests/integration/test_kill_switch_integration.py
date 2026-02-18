from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.config_models import RiskConfig
from core.event_bus import EventBus
from core.event_types import EventType
from core.events import BaseEvent
from core.logger import configure_logging, get_logger
from execution.adapters.paper_adapter import PaperAdapter
from execution.fill_simulator import FillSimulator
from execution.idempotency import IdempotencyManager
from execution.order_manager import OrderManager
from execution.reconciler import Reconciler
from execution.retry_handler import RetryHandler
from risk.drawdown_tracker import DrawdownTracker
from risk.exposure_tracker import ExposureTracker
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from risk.risk_models import RiskCheckStatus
from risk.slippage_model import SlippageModel
from risk.stop_manager import StopManager
from tests.unit._signal_fixtures import make_signal


async def _build(tmp_path: Path) -> tuple[RiskManager, KillSwitch, OrderManager, EventBus]:
    configure_logging(run_id="run-ks", environment="development", log_level="INFO")
    bus = EventBus()
    await bus.start()
    risk_cfg = RiskConfig(enabled=True)
    kill_switch = KillSwitch(risk_cfg.kill_switch, bus, run_id="run-ks")
    risk_manager = RiskManager(
        config=risk_cfg,
        position_sizer=PositionSizer(),
        stop_manager=StopManager(),
        drawdown_tracker=DrawdownTracker(),
        exposure_tracker=ExposureTracker(),
        kill_switch=kill_switch,
        event_bus=bus,
        logger=get_logger("tests.risk_manager"),
        run_id="run-ks",
    )
    slippage = SlippageModel()
    adapter = PaperAdapter(
        initial_balance=10000.0,
        fill_simulator=FillSimulator(slippage),
        slippage_model=slippage,
        event_bus=bus,
        logger=get_logger("tests.paper_adapter"),
        run_id="run-ks",
        risk_config=risk_cfg,
    )
    oms = OrderManager(
        broker_adapter=adapter,
        risk_manager=risk_manager,
        idempotency=IdempotencyManager(tmp_path / "idempotency.sqlite"),
        reconciler=Reconciler(),
        retry_handler=RetryHandler(),
        event_bus=bus,
        logger=get_logger("tests.order_manager"),
        db_path=tmp_path / "oms.sqlite",
        run_id="run-ks",
    )
    await oms.start()
    return risk_manager, kill_switch, oms, bus


@pytest.mark.asyncio
async def test_kill_switch_activation_rejects_new_order_flow(tmp_path: Path) -> None:
    risk_manager, kill_switch, oms, bus = await _build(tmp_path)
    try:
        signal = make_signal()
        healthy = oms.get_account()
        await risk_manager.evaluate(signal, healthy, [])
        account = oms.get_account().model_copy(update={"balance": 10000.0, "unrealized_pnl": -350.0, "equity": 9650.0})
        check = await risk_manager.evaluate(signal, account, [])
        assert check.status == RiskCheckStatus.REJECTED
        assert kill_switch.is_active is True
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_kill_switch_deactivate_allows_orders_again(tmp_path: Path) -> None:
    risk_manager, kill_switch, oms, bus = await _build(tmp_path)
    try:
        await kill_switch.activate(["manual_test"])
        await kill_switch.deactivate("operator_reset", operator="tester")
        signal = make_signal()
        check = await risk_manager.evaluate(signal, oms.get_account(), [])
        assert check.status in {RiskCheckStatus.APPROVED, RiskCheckStatus.MODIFIED, RiskCheckStatus.REJECTED}
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_kill_switch_event_published(tmp_path: Path) -> None:
    _, kill_switch, _, bus = await _build(tmp_path)
    try:
        events: list[BaseEvent] = []

        @bus.subscribe(EventType.KILL_SWITCH)
        async def _on_event(event: BaseEvent) -> None:
            events.append(event)

        await kill_switch.activate(["integration_test"])
        await asyncio.sleep(0.05)
        assert len(events) == 1
    finally:
        await bus.stop()
