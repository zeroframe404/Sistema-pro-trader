from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from core.event_bus import EventBus
from core.event_types import EventType
from core.events import BaseEvent
from execution.order_models import Account
from risk.kill_switch import KillSwitch


def _account(equity: float = 10000.0) -> Account:
    return Account(
        account_id="paper",
        broker="paper",
        balance=10000.0,
        unrealized_pnl=equity - 10000.0,
        margin_used=0.0,
        currency="USD",
        is_paper=True,
        leverage=100.0,
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_kill_switch_initially_inactive_and_activate_publishes_event() -> None:
    from core.config_models import KillSwitchConfig

    bus = EventBus()
    await bus.start()
    received: list[BaseEvent] = []

    @bus.subscribe(EventType.KILL_SWITCH)
    async def _on_event(event: BaseEvent) -> None:
        received.append(event)

    ks = KillSwitch(KillSwitchConfig(), bus, run_id="run-test")
    assert ks.is_active is False
    await ks.activate(["manual_test"])
    await asyncio.sleep(0.05)
    assert ks.is_active is True
    assert len(received) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_kill_switch_activates_on_drawdown_and_consecutive_losses() -> None:
    from core.config_models import KillSwitchConfig

    bus = EventBus()
    await bus.start()
    ks = KillSwitch(KillSwitchConfig(max_consecutive_losses=7), bus)
    should, reasons = await ks.check(
        account=_account(9700.0),
        open_positions=[],
        system_metrics={
            "daily_drawdown_pct": 3.5,
            "max_daily_drawdown_pct": 3.0,
            "consecutive_losses": 8,
        },
    )
    assert should is True
    assert "daily_drawdown_limit" in reasons
    assert "max_consecutive_losses" in reasons
    assert ks.is_active is True
    await bus.stop()


@pytest.mark.asyncio
async def test_kill_switch_api_error_rate_and_deactivate() -> None:
    from core.config_models import KillSwitchConfig

    bus = EventBus()
    await bus.start()
    ks = KillSwitch(KillSwitchConfig(max_api_error_rate_pct=20.0), bus)
    should, reasons = await ks.check(
        account=_account(),
        open_positions=[],
        system_metrics={"api_error_rate_pct": 25.0},
    )
    assert should is True
    assert "api_error_rate" in reasons
    await ks.deactivate(reason="manual_reset", operator="tester")
    assert ks.is_active is False
    await bus.stop()
