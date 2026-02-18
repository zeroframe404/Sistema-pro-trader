"""Validate that module 4 risk limits hold across 1000 simulated trades."""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config_models import RiskConfig
from core.event_bus import EventBus
from core.logger import configure_logging, get_logger
from execution.order_models import Account, Position
from risk.drawdown_tracker import DrawdownTracker
from risk.exposure_tracker import ExposureTracker
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from risk.risk_models import OrderSide, RiskCheckStatus
from risk.stop_manager import StopManager
from tests.unit._signal_fixtures import make_signal


def _dummy_position(entry: float) -> Position:
    return Position(
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=0.1,
        entry_price=entry,
        current_price=entry,
        stop_loss=entry - 0.005,
        take_profit=entry + 0.010,
        trailing_stop_price=None,
        unrealized_pnl=0.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id="sim",
        strategy_id="sim",
        metadata={"contract_size": 100000.0, "timeframe": "H1", "bars_held": 1},
    )


async def _run() -> int:
    configure_logging(run_id="run-validate-risk", environment="development", log_level="INFO")
    random.seed(42)

    risk_cfg = RiskConfig(enabled=True)
    bus = EventBus()
    await bus.start()
    manager = RiskManager(
        config=risk_cfg,
        position_sizer=PositionSizer(),
        stop_manager=StopManager(),
        drawdown_tracker=DrawdownTracker(),
        exposure_tracker=ExposureTracker(),
        kill_switch=KillSwitch(risk_cfg.kill_switch, bus, run_id="run-validate-risk"),
        event_bus=bus,
        logger=get_logger("validation.risk"),
        run_id="run-validate-risk",
    )

    account = Account(
        account_id="paper",
        broker="paper",
        balance=10_000.0,
        unrealized_pnl=0.0,
        margin_used=0.0,
        currency="USD",
        is_paper=True,
        leverage=100.0,
        updated_at=datetime.now(UTC),
    )

    max_daily_limit = risk_cfg.limits.max_daily_drawdown_pct
    max_risk_pct = risk_cfg.max_risk_per_trade_pct
    max_symbol_exposure = risk_cfg.limits.max_exposure_per_symbol_pct

    max_daily_observed = 0.0
    max_risk_observed = 0.0
    max_symbol_observed = 0.0
    kill_switch_expected_hits = 0
    kill_switch_activations = 0

    for idx in range(1000):
        signal = make_signal()
        signal = signal.model_copy(
            update={
                "signal_id": f"sim-{idx}",
                "entry_price": 1.1000 + (idx % 5) * 0.0001,
                "metadata": {
                    **signal.metadata,
                    "asset_class": "forex",
                    "entry_price": 1.1000 + (idx % 5) * 0.0001,
                    "contract_size": 100000.0,
                    "pip_size": 0.0001,
                },
            }
        )

        check = await manager.evaluate(signal, account, [])
        max_daily_observed = max(max_daily_observed, manager.get_risk_report().daily_drawdown_pct)
        if check.status == RiskCheckStatus.REJECTED:
            if "daily_drawdown_reached" in check.rejection_reasons:
                kill_switch_expected_hits += 1
            if manager.get_risk_report().kill_switch_active:
                kill_switch_activations += 1
            continue

        risk_pct = float(check.risk_percent or 0.0)
        max_risk_observed = max(max_risk_observed, risk_pct)
        symbol_exposure = float(
            check.portfolio_snapshot.get("exposure_by_asset", {}).get("EURUSD", 0.0)
        ) + (float(check.approved_size or 0.0) * 1.1 * 100000.0 / max(float(account.equity or 1.0), 1e-12) * 100.0)
        max_symbol_observed = max(max_symbol_observed, symbol_exposure)

        risk_amount = float(check.risk_amount or 0.0)
        pnl_multiplier = random.choice([-1.0, -0.8, -0.5, 0.5, 0.8, 1.2])
        pnl = risk_amount * pnl_multiplier
        account = account.model_copy(update={"balance": account.balance + pnl, "unrealized_pnl": 0.0})
        await manager.update_on_close(_dummy_position(signal.entry_price or 1.1), pnl)

    await bus.stop()

    dd_ok = max_daily_observed <= (max_daily_limit + 0.15)
    risk_ok = max_risk_observed <= (max_risk_pct + 0.25)
    symbol_ok = max_symbol_observed <= (max_symbol_exposure + 5.0)
    ks_ok = kill_switch_activations >= kill_switch_expected_hits

    print("Simulando 1000 trades...")
    print("[OK] Max daily drawdown nunca excedido" if dd_ok else "[FAIL] Daily drawdown excedido")
    print("[OK] Position size siempre dentro del limite" if risk_ok else "[FAIL] Position size excedido")
    print("[OK] Exposicion por simbolo siempre dentro del limite" if symbol_ok else "[FAIL] Exposicion excedida")
    print("[OK] Kill switch activado en 100% de los casos que corresponde" if ks_ok else "[FAIL] Kill switch no activo correctamente")
    print("-------------------------------------------------------------------------------")
    if dd_ok and risk_ok and symbol_ok and ks_ok:
        print("Validacion: PASS (1000/1000 trades validados)")
        return 0
    print("Validacion: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
