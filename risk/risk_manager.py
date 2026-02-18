"""Risk manager orchestration for signal -> order pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from structlog.stdlib import BoundLogger

from core.config_models import RiskConfig
from core.event_bus import EventBus
from core.logger import get_logger
from data.asset_types import AssetClass
from data.models import AssetInfo
from execution.order_models import Account, Fill, Position
from risk.drawdown_tracker import DrawdownTracker
from risk.exposure_tracker import ExposureTracker
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer
from risk.risk_models import (
    OrderSide,
    PositionSizingMethod,
    RiskCheck,
    RiskCheckStatus,
    RiskReport,
)
from risk.stop_manager import StopManager
from signals.signal_models import Signal, SignalDirection


class RiskManager:
    """Validate and size signals against portfolio and system risk constraints."""

    def __init__(
        self,
        config: RiskConfig,
        position_sizer: PositionSizer,
        stop_manager: StopManager,
        drawdown_tracker: DrawdownTracker,
        exposure_tracker: ExposureTracker,
        kill_switch: KillSwitch,
        event_bus: EventBus,
        logger: BoundLogger | None = None,
        run_id: str = "unknown",
    ) -> None:
        self._config = config
        self._position_sizer = position_sizer
        self._stop_manager = stop_manager
        self._drawdown_tracker = drawdown_tracker
        self._exposure_tracker = exposure_tracker
        self._kill_switch = kill_switch
        self._event_bus = event_bus
        self._logger = logger or get_logger("risk.manager")
        self._run_id = run_id
        self._consecutive_losses = 0
        self._last_report: RiskReport | None = None

    async def evaluate(
        self,
        signal: Signal,
        account: Account,
        open_positions: list[Position],
        current_atr: float | None = None,
        support_resistance: list[float] | None = None,
    ) -> RiskCheck:
        """Validate a signal under risk rules and return a deterministic RiskCheck."""

        now = datetime.now(UTC)
        self._drawdown_tracker.update(float(account.equity or 0.0), now)

        if self._kill_switch.is_active:
            return self._rejected(signal, ["kill_switch_active"], account, open_positions)

        if signal.direction not in {SignalDirection.BUY, SignalDirection.SELL}:
            return self._rejected(signal, ["non_actionable_signal_direction"], account, open_positions)

        side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL

        drawdown_violations = await self._check_drawdown_limits(account)
        if drawdown_violations:
            await self._kill_switch.activate(drawdown_violations)
            await self._kill_switch.check(
                account=account,
                open_positions=open_positions,
                system_metrics={
                    "daily_drawdown_pct": self._drawdown_tracker.daily_drawdown_pct,
                    "weekly_drawdown_pct": self._drawdown_tracker.weekly_drawdown_pct,
                    "max_daily_drawdown_pct": self._config.limits.max_daily_drawdown_pct,
                    "max_weekly_drawdown_pct": self._config.limits.max_weekly_drawdown_pct,
                    "min_equity_threshold_pct": self._config.limits.min_equity_threshold_pct,
                    "initial_balance": account.balance,
                    "consecutive_losses": self._consecutive_losses,
                },
            )
            return self._rejected(signal, drawdown_violations, account, open_positions)

        if len(open_positions) >= self._config.limits.max_open_positions:
            return self._rejected(signal, ["max_open_positions_reached"], account, open_positions)

        entry_price = self._resolve_entry_price(signal)
        if entry_price <= 0:
            return self._rejected(signal, ["invalid_entry_price"], account, open_positions)

        asset_class = self._resolve_asset_class(signal)
        asset_info = self._resolve_asset_info(signal, asset_class)
        atr = max(float(current_atr or signal.metadata.get("atr", entry_price * 0.001)), entry_price * 0.0001)

        stop_loss, take_profit, trailing = self._stop_manager.calculate_stops(
            symbol=signal.symbol,
            side=side,
            entry_price=entry_price,
            atr=atr,
            asset_info=asset_info,
            config=self._config.stop_config(),
            support_resistance=support_resistance,
        )
        rr_ratio = self._stop_manager.calculate_rr_ratio(entry_price, stop_loss, take_profit, side)
        if rr_ratio + 1e-9 < self._config.min_rr_ratio:
            return self._rejected(signal, ["min_rr_ratio_not_met"], account, open_positions)

        method, sizing_params = self._resolve_sizing_method(signal, asset_class)
        sized = self._position_sizer.calculate(
            method=method,
            symbol=signal.symbol,
            asset_class=asset_class,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            equity=float(account.equity or 0.0),
            asset_info=asset_info,
            atr=atr,
            win_rate=float(signal.metadata.get("win_rate", 0.55)),
            avg_win_loss_ratio=float(signal.metadata.get("avg_win_loss_ratio", 1.5)),
            max_position_pct=self._config.limits.max_exposure_per_symbol_pct / 100.0,
            max_risk_per_trade_pct=self._config.max_risk_per_trade_pct / 100.0,
            **sizing_params,
        )

        if sized.units <= 0:
            return self._rejected(signal, ["position_size_is_zero"], account, open_positions)

        exposure_violations = await self._check_exposure_limits(
            symbol=signal.symbol,
            asset_class=asset_class,
            proposed_size=sized.notional_value,
            open_positions=open_positions,
            account=account,
        )

        status = RiskCheckStatus.APPROVED
        warnings = list(sized.warnings)
        rejection_reasons: list[str] = []
        if exposure_violations:
            reduced = sized.model_copy(
                update={
                    "units": sized.units * 0.5,
                    "notional_value": sized.notional_value * 0.5,
                    "risk_amount": sized.risk_amount * 0.5,
                    "risk_percent": sized.risk_percent * 0.5,
                    "was_capped": True,
                    "cap_reason": "exposure_limit_reduction",
                }
            )
            recheck = await self._check_exposure_limits(
                symbol=signal.symbol,
                asset_class=asset_class,
                proposed_size=reduced.notional_value,
                open_positions=open_positions,
                account=account,
            )
            if recheck:
                rejection_reasons = exposure_violations
                return self._rejected(signal, rejection_reasons, account, open_positions)
            sized = reduced
            status = RiskCheckStatus.MODIFIED
            warnings.extend(exposure_violations)

        if sized.was_capped and status == RiskCheckStatus.APPROVED:
            status = RiskCheckStatus.MODIFIED

        return RiskCheck(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            broker=signal.broker,
            status=status,
            approved_size=sized.units,
            approved_side=side,
            suggested_sl=stop_loss,
            suggested_tp=take_profit,
            suggested_trailing=trailing,
            risk_amount=sized.risk_amount,
            risk_percent=sized.risk_percent * 100.0,
            reward_risk_ratio=rr_ratio,
            rejection_reasons=rejection_reasons,
            warnings=warnings,
            portfolio_snapshot=self._portfolio_snapshot(account, open_positions),
        )

    async def update_on_fill(self, fill: Fill) -> None:
        """Update internal trackers when a fill is received."""

        _ = fill
        self._logger.debug("risk_update_on_fill")

    async def update_on_close(self, position: Position, pnl: float) -> None:
        """Update trackers when a position closes."""

        self._exposure_tracker.remove_position(position.position_id)
        self._drawdown_tracker.register_trade_close(pnl, datetime.now(UTC))
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    async def monitor_open_positions(
        self,
        open_positions: list[Position],
        current_prices: dict[str, float],
        current_atrs: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Return list of recommended actions over open positions."""

        actions: list[dict[str, Any]] = []
        trailing_cfg = self._config.trailing_config()
        time_cfg = self._config.time_exit_config()
        now = datetime.now(UTC)

        for position in open_positions:
            price = current_prices.get(position.symbol)
            if price is not None:
                new_sl = self._stop_manager.should_trail(
                    position=position,
                    current_price=price,
                    atr=float(current_atrs.get(position.symbol, max(price * 0.001, 1e-9))),
                    config=trailing_cfg,
                )
                if new_sl is not None:
                    actions.append({"position_id": position.position_id, "action": "update_trailing", "new_sl": new_sl})

                should_exit, reason = self._stop_manager.should_exit_by_time(position, now, time_cfg)
                if should_exit:
                    actions.append({"position_id": position.position_id, "action": "close", "reason": reason})

        return actions

    def get_risk_report(self) -> RiskReport:
        """Return current portfolio risk report."""

        if self._last_report is not None:
            return self._last_report
        return RiskReport(
            run_id=self._run_id,
            equity=0.0,
            balance=0.0,
            unrealized_pnl=0.0,
            realized_pnl_today=0.0,
            realized_pnl_week=0.0,
            daily_drawdown_pct=0.0,
            weekly_drawdown_pct=0.0,
            max_drawdown_pct=0.0,
            current_drawdown_pct=0.0,
            open_positions_count=0,
            total_exposure_notional=0.0,
            total_exposure_pct=0.0,
            exposure_by_asset={},
            exposure_by_asset_class={},
            limits_status={},
            kill_switch_active=self._kill_switch.is_active,
            kill_switch_reasons=cast(list[str], self._kill_switch.get_status().get("reasons", [])),
        )

    async def _check_drawdown_limits(self, account: Account) -> list[str]:
        violations: list[str] = []
        if self._drawdown_tracker.is_daily_limit_reached(self._config.limits.max_daily_drawdown_pct):
            violations.append("daily_drawdown_reached")
        if self._drawdown_tracker.is_weekly_limit_reached(self._config.limits.max_weekly_drawdown_pct):
            violations.append("weekly_drawdown_reached")

        initial_balance = account.balance if account.balance > 0 else 1.0
        equity_pct = (float(account.equity or 0.0) / initial_balance) * 100.0
        if equity_pct < self._config.limits.min_equity_threshold_pct:
            violations.append("min_equity_threshold_reached")
        return violations

    async def _check_exposure_limits(
        self,
        symbol: str,
        asset_class: AssetClass,
        proposed_size: float,
        open_positions: list[Position],
        account: Account,
    ) -> list[str]:
        for position in open_positions:
            self._exposure_tracker.add_position(position)

        return self._exposure_tracker.would_exceed_limits(
            symbol=symbol,
            asset_class=asset_class,
            new_exposure_notional=proposed_size,
            equity=float(account.equity or 0.0),
            limits=self._config.limits.to_exposure_limits(),
        )

    def _portfolio_snapshot(self, account: Account, open_positions: list[Position]) -> dict[str, Any]:
        equity = float(account.equity or 0.0)
        total_notional = sum(abs(item.quantity * item.current_price) for item in open_positions)
        exposure_by_asset: dict[str, float] = {}
        for position in open_positions:
            exposure_by_asset[position.symbol] = exposure_by_asset.get(position.symbol, 0.0) + (
                abs(position.quantity * position.current_price) / equity * 100.0 if equity > 0 else 0.0
            )
        exposure_by_class = self._exposure_tracker.get_exposure_by_asset_class(equity)
        limits_status = {
            "max_daily_drawdown_pct": {
                "used": self._drawdown_tracker.daily_drawdown_pct,
                "limit": self._config.limits.max_daily_drawdown_pct,
                "pct": (self._drawdown_tracker.daily_drawdown_pct / max(self._config.limits.max_daily_drawdown_pct, 1e-12)),
            },
            "max_weekly_drawdown_pct": {
                "used": self._drawdown_tracker.weekly_drawdown_pct,
                "limit": self._config.limits.max_weekly_drawdown_pct,
                "pct": (self._drawdown_tracker.weekly_drawdown_pct / max(self._config.limits.max_weekly_drawdown_pct, 1e-12)),
            },
        }
        report = RiskReport(
            run_id=self._run_id,
            equity=equity,
            balance=account.balance,
            unrealized_pnl=account.unrealized_pnl,
            realized_pnl_today=self._drawdown_tracker.realized_pnl_today,
            realized_pnl_week=self._drawdown_tracker.realized_pnl_week,
            daily_drawdown_pct=self._drawdown_tracker.daily_drawdown_pct,
            weekly_drawdown_pct=self._drawdown_tracker.weekly_drawdown_pct,
            max_drawdown_pct=self._drawdown_tracker.max_drawdown_pct,
            current_drawdown_pct=self._drawdown_tracker.session_drawdown_pct,
            open_positions_count=len(open_positions),
            total_exposure_notional=total_notional,
            total_exposure_pct=(total_notional / equity * 100.0) if equity > 0 else 0.0,
            exposure_by_asset=exposure_by_asset,
            exposure_by_asset_class=exposure_by_class,
            limits_status=limits_status,
            kill_switch_active=self._kill_switch.is_active,
            kill_switch_reasons=cast(list[str], self._kill_switch.get_status().get("reasons", [])),
        )
        self._last_report = report
        return report.model_dump(mode="python")

    def _resolve_sizing_method(self, signal: Signal, asset_class: AssetClass) -> tuple[PositionSizingMethod, dict[str, Any]]:
        override = self._config.sizing_overrides.get(asset_class.value)
        if override is not None:
            params: dict[str, Any] = {}
            if override.amount is not None:
                params["amount"] = override.amount
            if override.pct is not None:
                params["pct"] = override.pct
            if override.risk_pct is not None:
                params["risk_pct"] = override.risk_pct
            return PositionSizingMethod(override.method.value), params

        method = PositionSizingMethod(self._config.default_sizing_method.value)
        return method, {"risk_pct": self._config.default_risk_per_trade_pct, "kelly_fraction": self._config.kelly_fraction}

    @staticmethod
    def _resolve_entry_price(signal: Signal) -> float:
        if signal.entry_price is not None and signal.entry_price > 0:
            return signal.entry_price
        maybe = signal.metadata.get("entry_price")
        if isinstance(maybe, (int, float)) and float(maybe) > 0:
            return float(maybe)
        maybe_last = signal.metadata.get("last_price")
        if isinstance(maybe_last, (int, float)) and float(maybe_last) > 0:
            return float(maybe_last)
        return 0.0

    @staticmethod
    def _resolve_asset_class(signal: Signal) -> AssetClass:
        raw = signal.metadata.get("asset_class")
        if isinstance(raw, str):
            try:
                return AssetClass(raw)
            except ValueError:
                return AssetClass.UNKNOWN
        return AssetClass.UNKNOWN

    @staticmethod
    def _resolve_asset_info(signal: Signal, asset_class: AssetClass) -> AssetInfo:
        contract_size = 100000.0 if asset_class == AssetClass.FOREX else 1.0
        pip_size = 0.0001 if asset_class == AssetClass.FOREX else 0.01
        return AssetInfo(
            symbol=signal.symbol,
            broker=signal.broker,
            name=signal.symbol,
            asset_class=asset_class,
            currency="USD",
            contract_size=contract_size,
            min_volume=0.01,
            max_volume=1_000_000.0,
            volume_step=0.01,
            pip_size=pip_size,
            digits=5 if asset_class == AssetClass.FOREX else 2,
            trading_hours={},
            available_timeframes=[],
            supported_order_types=["MARKET", "LIMIT", "STOP"],
        )

    def _rejected(
        self,
        signal: Signal,
        reasons: list[str],
        account: Account,
        open_positions: list[Position],
    ) -> RiskCheck:
        return RiskCheck(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            broker=signal.broker,
            status=RiskCheckStatus.REJECTED,
            approved_size=0.0,
            approved_side=None,
            rejection_reasons=reasons,
            warnings=[],
            portfolio_snapshot=self._portfolio_snapshot(account, open_positions),
        )
