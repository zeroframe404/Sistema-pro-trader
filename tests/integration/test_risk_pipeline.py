from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.config_models import RiskConfig
from core.event_bus import EventBus
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


async def _build_pipeline(tmp_path: Path) -> tuple[RiskManager, OrderManager, EventBus]:
    configure_logging(run_id="run-risk-pipeline", environment="development", log_level="INFO")
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
        run_id="run-risk-pipeline",
        risk_config=risk_cfg,
    )
    manager = RiskManager(
        config=risk_cfg,
        position_sizer=PositionSizer(),
        stop_manager=StopManager(),
        drawdown_tracker=DrawdownTracker(),
        exposure_tracker=ExposureTracker(),
        kill_switch=KillSwitch(risk_cfg.kill_switch, bus, run_id="run-risk-pipeline"),
        event_bus=bus,
        logger=get_logger("tests.risk_manager"),
        run_id="run-risk-pipeline",
    )
    oms = OrderManager(
        broker_adapter=adapter,
        risk_manager=manager,
        idempotency=IdempotencyManager(tmp_path / "idempotency.sqlite"),
        reconciler=Reconciler(),
        retry_handler=RetryHandler(),
        event_bus=bus,
        logger=get_logger("tests.order_manager"),
        db_path=tmp_path / "oms.sqlite",
        run_id="run-risk-pipeline",
    )
    await oms.start()
    return manager, oms, bus


@pytest.mark.asyncio
async def test_signal_to_risk_to_order_pipeline(tmp_path: Path) -> None:
    risk_manager, oms, bus = await _build_pipeline(tmp_path)
    try:
        signal = make_signal()
        account = oms.get_account()
        check = await risk_manager.evaluate(signal, account, oms.get_open_positions(), current_atr=0.001)
        assert check.status in {RiskCheckStatus.APPROVED, RiskCheckStatus.MODIFIED}
        if check.status != RiskCheckStatus.REJECTED:
            order = await oms.submit_from_signal(signal, check, account)
            assert order.status.value in {"submitted", "filled", "partially_filled"}
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_drawdown_limit_rejects_signal(tmp_path: Path) -> None:
    risk_manager, oms, bus = await _build_pipeline(tmp_path)
    try:
        signal = make_signal()
        healthy = oms.get_account()
        await risk_manager.evaluate(signal, healthy, oms.get_open_positions(), current_atr=0.001)
        stressed = healthy.model_copy(update={"balance": 10000.0, "unrealized_pnl": -400.0, "equity": 9600.0})
        check = await risk_manager.evaluate(signal, stressed, oms.get_open_positions(), current_atr=0.001)
        assert check.status == RiskCheckStatus.REJECTED
        assert "daily_drawdown_reached" in check.rejection_reasons or "min_equity_threshold_reached" in check.rejection_reasons
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_pipeline_latency_under_200ms(tmp_path: Path) -> None:
    risk_manager, oms, bus = await _build_pipeline(tmp_path)
    try:
        signal = make_signal()
        account = oms.get_account()
        start = time.perf_counter()
        check = await risk_manager.evaluate(signal, account, oms.get_open_positions(), current_atr=0.001)
        if check.status != RiskCheckStatus.REJECTED:
            await oms.submit_from_signal(signal, check, account)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert elapsed_ms < 200.0
    finally:
        await bus.stop()
