from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.config_models import RiskConfig
from core.event_bus import EventBus
from core.logger import configure_logging, get_logger
from data.models import Tick
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


async def _build(tmp_path: Path) -> tuple[OrderManager, RiskManager, PaperAdapter, EventBus]:
    configure_logging(run_id="run-paper", environment="development", log_level="INFO")
    bus = EventBus()
    await bus.start()
    risk_cfg = RiskConfig(enabled=True)
    slippage = SlippageModel()
    adapter = PaperAdapter(
        initial_balance=10000.0,
        fill_simulator=FillSimulator(slippage),
        slippage_model=slippage,
        event_bus=bus,
        logger=get_logger("tests.paper_adapter"),
        run_id="run-paper",
        risk_config=risk_cfg,
    )
    risk_manager = RiskManager(
        config=risk_cfg,
        position_sizer=PositionSizer(),
        stop_manager=StopManager(),
        drawdown_tracker=DrawdownTracker(),
        exposure_tracker=ExposureTracker(),
        kill_switch=KillSwitch(risk_cfg.kill_switch, bus, run_id="run-paper"),
        event_bus=bus,
        logger=get_logger("tests.risk_manager"),
        run_id="run-paper",
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
        run_id="run-paper",
    )
    await oms.start()
    return oms, risk_manager, adapter, bus


@pytest.mark.asyncio
async def test_full_paper_cycle_signal_to_close(tmp_path: Path) -> None:
    oms, risk_manager, adapter, bus = await _build(tmp_path)
    try:
        signal = make_signal()
        account = oms.get_account()
        check = await risk_manager.evaluate(signal, account, [], current_atr=0.001)
        assert check.status in {RiskCheckStatus.APPROVED, RiskCheckStatus.MODIFIED}
        order = await oms.submit_from_signal(signal, check, account)
        assert order.status.value in {"submitted", "filled", "partially_filled"}

        positions = oms.get_open_positions()
        assert positions
        p = positions[0]
        tick = Tick(
            symbol=p.symbol,
            broker=p.broker,
            timestamp=datetime.now(UTC),
            bid=float(p.take_profit or p.current_price + 0.01),
            ask=float(p.take_profit or p.current_price + 0.01),
            last=float(p.take_profit or p.current_price + 0.01),
            volume=1.0,
            spread=0.0,
            source="test",
        )
        await adapter.process_tick(tick)
        assert oms.get_account().equity is not None
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_reconciler_clean_for_paper_adapter(tmp_path: Path) -> None:
    oms, _, _, bus = await _build(tmp_path)
    try:
        sync = await oms.sync_with_broker()
        assert sync["report"]["is_clean"] is True
    finally:
        await bus.stop()
