"""Emergency kill-switch for risk module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.config_models import KillSwitchConfig
from core.event_bus import EventBus
from core.events import KillSwitchEvent
from execution.order_models import Account, Position


class KillSwitch:
    """Stop all new orders under critical risk/system conditions."""

    def __init__(self, config: KillSwitchConfig, event_bus: EventBus, run_id: str = "unknown") -> None:
        self._config = config
        self._event_bus = event_bus
        self._run_id = run_id
        self._active = False
        self._reasons: list[str] = []
        self._activated_at: datetime | None = None
        self._deactivated_at: datetime | None = None
        self._deactivated_by: str | None = None
        self._deactivation_reason: str | None = None

    @property
    def is_active(self) -> bool:
        """Current activation flag."""

        return self._active

    async def check(
        self,
        account: Account,
        open_positions: list[Position],
        system_metrics: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Evaluate whether kill switch should be activated."""

        _ = open_positions
        reasons: list[str] = []

        daily_dd = float(system_metrics.get("daily_drawdown_pct", 0.0))
        max_daily = float(system_metrics.get("max_daily_drawdown_pct", 0.0))
        if max_daily > 0 and daily_dd >= max_daily:
            reasons.append("daily_drawdown_limit")

        weekly_dd = float(system_metrics.get("weekly_drawdown_pct", 0.0))
        max_weekly = float(system_metrics.get("max_weekly_drawdown_pct", 0.0))
        if max_weekly > 0 and weekly_dd >= max_weekly:
            reasons.append("weekly_drawdown_limit")

        initial_balance = float(system_metrics.get("initial_balance", account.balance))
        min_equity_threshold_pct = float(system_metrics.get("min_equity_threshold_pct", 0.0))
        if initial_balance > 0 and min_equity_threshold_pct > 0:
            equity_pct = (float(account.equity or 0.0) / initial_balance) * 100.0
            if equity_pct < min_equity_threshold_pct:
                reasons.append("equity_threshold_breach")

        consecutive_losses = int(system_metrics.get("consecutive_losses", 0))
        if consecutive_losses >= self._config.max_consecutive_losses:
            reasons.append("max_consecutive_losses")

        api_error_rate = float(system_metrics.get("api_error_rate_pct", 0.0))
        if api_error_rate >= self._config.max_api_error_rate_pct:
            reasons.append("api_error_rate")

        latency_ms = float(system_metrics.get("latency_ms", 0.0))
        if latency_ms >= self._config.max_latency_ms:
            reasons.append("latency_spike")

        fill_deviation_pct = float(system_metrics.get("fill_deviation_pct", 0.0))
        if fill_deviation_pct >= self._config.max_fill_deviation_pct:
            reasons.append("fill_deviation")

        equity_spike_pct = float(system_metrics.get("equity_spike_pct", 0.0))
        if equity_spike_pct >= self._config.max_equity_spike_pct:
            reasons.append("equity_spike")

        if bool(system_metrics.get("unexpected_fills", False)):
            reasons.append("unexpected_fills")

        should_activate = len(reasons) > 0
        if should_activate and not self._active:
            await self.activate(reasons, close_positions=system_metrics.get("close_positions"))
        return should_activate, reasons

    async def activate(self, reasons: list[str], close_positions: bool | None = None) -> None:
        """Activate kill switch and publish event."""

        if self._active:
            return
        self._active = True
        self._reasons = list(dict.fromkeys(reasons))
        self._activated_at = datetime.now(UTC)

        await self._event_bus.publish(
            KillSwitchEvent(
                source="risk.kill_switch",
                run_id=self._run_id,
                reason="; ".join(self._reasons),
                triggered_by="risk_manager",
            )
        )

        _ = close_positions if close_positions is not None else self._config.auto_close_positions

    async def deactivate(self, reason: str, operator: str = "system") -> None:
        """Deactivate kill switch with explicit reason/operator."""

        self._active = False
        self._deactivated_at = datetime.now(UTC)
        self._deactivated_by = operator
        self._deactivation_reason = reason

    def get_status(self) -> dict[str, Any]:
        """Return full status payload."""

        return {
            "is_active": self._active,
            "reasons": list(self._reasons),
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
            "deactivated_at": self._deactivated_at.isoformat() if self._deactivated_at else None,
            "deactivated_by": self._deactivated_by,
            "deactivation_reason": self._deactivation_reason,
        }
