"""Demo runner for module 4 (Risk + OMS)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console

from core.config_models import RiskConfig
from core.event_bus import EventBus
from core.logger import configure_logging, get_logger
from data.models import Tick
from execution.adapters.paper_adapter import PaperAdapter
from execution.fill_simulator import FillSimulator
from execution.idempotency import IdempotencyManager
from execution.order_manager import OrderManager
from execution.order_models import Position
from execution.reconciler import Reconciler
from execution.retry_handler import RetryHandler
from risk.drawdown_tracker import DrawdownTracker
from risk.exposure_tracker import ExposureTracker
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from risk.risk_models import OrderSide, RiskCheckStatus
from risk.slippage_model import SlippageModel
from risk.stop_manager import StopManager
from tests.unit._signal_fixtures import make_signal


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Module 4 demo scenarios")
    parser.add_argument("--scenario", type=str, default="all", help="A|B|C|D|all")
    return parser.parse_args()


async def _build_runtime(tmp_dir: Path):
    risk_cfg = RiskConfig(enabled=True)
    bus = EventBus()
    await bus.start()
    slippage = SlippageModel()
    adapter = PaperAdapter(
        initial_balance=10000.0,
        fill_simulator=FillSimulator(slippage),
        slippage_model=slippage,
        event_bus=bus,
        logger=get_logger("demo.paper_adapter"),
        run_id="run-module4-demo",
        risk_config=risk_cfg,
    )
    risk_manager = RiskManager(
        config=risk_cfg,
        position_sizer=PositionSizer(),
        stop_manager=StopManager(),
        drawdown_tracker=DrawdownTracker(),
        exposure_tracker=ExposureTracker(),
        kill_switch=KillSwitch(risk_cfg.kill_switch, bus, run_id="run-module4-demo"),
        event_bus=bus,
        logger=get_logger("demo.risk"),
        run_id="run-module4-demo",
    )
    order_manager = OrderManager(
        broker_adapter=adapter,
        risk_manager=risk_manager,
        idempotency=IdempotencyManager(tmp_dir / "idempotency.sqlite"),
        reconciler=Reconciler(),
        retry_handler=RetryHandler(),
        event_bus=bus,
        logger=get_logger("demo.oms"),
        db_path=tmp_dir / "oms.sqlite",
        run_id="run-module4-demo",
    )
    await order_manager.start()
    return risk_cfg, bus, adapter, risk_manager, order_manager


async def _scenario_a(console: Console, runtime) -> bool:
    _, _, adapter, risk_manager, oms = runtime
    console.print("\n[bold]SCENARIO A: Ciclo completo paper trading[/bold]")

    signal = make_signal()
    account = oms.get_account()
    check = await risk_manager.evaluate(signal, account, [])
    if check.status == RiskCheckStatus.REJECTED:
        console.print(f"[red]Risk rejected: {check.rejection_reasons}[/red]")
        return False

    order = await oms.submit_from_signal(signal, check, account)
    console.print(f"Signal: {signal.symbol} {signal.direction.value} ({int(signal.confidence*100)}%)")
    console.print(f"Risk check: [green]{check.status.value.upper()}[/green] | Size={check.approved_size:.4f}")
    console.print(f"Order: {order.order_id} status={order.status.value}")

    positions = oms.get_open_positions()
    if not positions:
        console.print("[red]No open position after submit[/red]")
        return False
    position = positions[0]
    console.print(f"Position opened: {position.symbol} {position.side.value} qty={position.quantity:.4f}")

    up_tick = Tick(
        symbol=position.symbol,
        broker=position.broker,
        timestamp=datetime.now(UTC),
        bid=position.current_price + 0.0040,
        ask=position.current_price + 0.0041,
        last=position.current_price + 0.0040,
        volume=1.0,
        spread=0.0001,
        source="demo",
    )
    await adapter.process_tick(up_tick)
    actions = await risk_manager.monitor_open_positions(
        open_positions=oms.get_open_positions(),
        current_prices={position.symbol: up_tick.last or up_tick.bid},
        current_atrs={position.symbol: 0.001},
    )
    if actions:
        console.print(f"Trailing actions: {actions}")
    down_tick = Tick(
        symbol=position.symbol,
        broker=position.broker,
        timestamp=datetime.now(UTC),
        bid=position.current_price - 0.0100,
        ask=position.current_price - 0.0099,
        last=position.current_price - 0.0100,
        volume=1.0,
        spread=0.0001,
        source="demo",
    )
    await adapter.process_tick(down_tick)
    console.print("[green]Scenario A PASS[/green]")
    return True


async def _scenario_b(console: Console, runtime) -> bool:
    _, _, _, risk_manager, oms = runtime
    console.print("\n[bold]SCENARIO B: Kill Switch[/bold]")
    signal = make_signal()
    healthy = oms.get_account()
    await risk_manager.evaluate(signal, healthy, [])
    stressed = healthy.model_copy(update={"balance": 10000.0, "unrealized_pnl": -350.0, "equity": 9650.0})
    check = await risk_manager.evaluate(signal, stressed, [])
    if check.status != RiskCheckStatus.REJECTED:
        console.print("[red]Expected REJECTED under drawdown[/red]")
        return False
    console.print(f"Rejected reasons: {check.rejection_reasons}")
    if "kill_switch_active" not in check.rejection_reasons and "daily_drawdown_reached" not in check.rejection_reasons:
        console.print("[red]Kill switch reason not present[/red]")
        return False
    console.print("[green]Scenario B PASS[/green]")
    return True


async def _scenario_c(console: Console, runtime) -> bool:
    _, _, _, risk_manager, oms = runtime
    console.print("\n[bold]SCENARIO C: Límite de correlación[/bold]")
    if risk_manager._kill_switch.is_active:  # noqa: SLF001
        await risk_manager._kill_switch.deactivate("demo_reset", operator="demo")  # noqa: SLF001
    open_positions = [
        Position(
            symbol="EURUSD",
            broker="paper",
            side=OrderSide.BUY,
            quantity=0.5,
            entry_price=1.1,
            current_price=1.1,
            stop_loss=1.095,
            take_profit=1.105,
            trailing_stop_price=None,
            unrealized_pnl=0.0,
            realized_pnl=None,
            commission_total=0.0,
            signal_id="sig-1",
            strategy_id="s",
            metadata={"contract_size": 100000.0},
        ),
        Position(
            symbol="GBPUSD",
            broker="paper",
            side=OrderSide.BUY,
            quantity=0.5,
            entry_price=1.25,
            current_price=1.25,
            stop_loss=1.245,
            take_profit=1.255,
            trailing_stop_price=None,
            unrealized_pnl=0.0,
            realized_pnl=None,
            commission_total=0.0,
            signal_id="sig-2",
            strategy_id="s",
            metadata={"contract_size": 100000.0},
        ),
    ]
    signal = make_signal(symbol="AUDUSD")
    signal = signal.model_copy(update={"entry_price": 0.75, "metadata": {**signal.metadata, "asset_class": "forex"}})
    check = await risk_manager.evaluate(signal, oms.get_account(), open_positions)
    if check.status == RiskCheckStatus.REJECTED:
        console.print(f"Rejected as expected: {check.rejection_reasons}")
        console.print("[green]Scenario C PASS[/green]")
        return True
    if check.status == RiskCheckStatus.MODIFIED:
        console.print("Modified due to concentration limits.")
        console.print("[green]Scenario C PASS[/green]")
        return True
    console.print("[red]Expected modified/rejected under correlation pressure[/red]")
    return False


async def _scenario_d(console: Console, runtime) -> bool:
    _, _, _, _, _ = runtime
    console.print("\n[bold]SCENARIO D: Trailing stop logic[/bold]")
    manager = StopManager()
    position = Position(
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=0.2,
        entry_price=1.1000,
        current_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        trailing_stop_price=None,
        unrealized_pnl=0.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id="sig",
        strategy_id="s",
        metadata={"pip_size": 0.0001},
    )
    from core.config_models import TrailingConfig

    moved = manager.should_trail(position, 1.1050, 0.0010, TrailingConfig())
    not_moved = manager.should_trail(position, 1.0940, 0.0010, TrailingConfig())
    if moved is None or not_moved is not None:
        console.print("[red]Trailing logic did not behave as expected[/red]")
        return False
    console.print(f"Trailing moved to: {moved:.5f}")
    console.print("[green]Scenario D PASS[/green]")
    return True


async def _main() -> int:
    args = _parse_args()
    configure_logging(run_id="run-module4-demo", environment="development", log_level="INFO")
    console = Console()
    console.print("[bold]Auto Trading Pro - Modulo 4: Riesgo + OMS Demo[/bold]")
    runtime = await _build_runtime(Path("data_store") / "demo_module4")

    mapping = {"A": _scenario_a, "B": _scenario_b, "C": _scenario_c, "D": _scenario_d}
    selected = [args.scenario.upper()] if args.scenario.lower() != "all" else ["A", "B", "C", "D"]

    failed = []
    try:
        for item in selected:
            runner = mapping.get(item)
            if runner is None:
                console.print(f"[red]Unknown scenario: {item}[/red]")
                return 1
            ok = await runner(console, runtime)
            if not ok:
                failed.append(item)
    finally:
        await runtime[1].stop()

    if failed:
        console.print(f"[red]Failed scenarios: {failed}[/red]")
        return 1
    console.print("[green]Modulo 4 funcionando correctamente[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
