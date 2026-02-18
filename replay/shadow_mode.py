"""Shadow mode runtime for side-by-side strategy validation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from structlog.stdlib import BoundLogger

from backtest.backtest_models import BacktestMetrics, BacktestTrade
from backtest.metrics import MetricsCalculator
from core.event_bus import EventBus
from core.event_types import EventType
from core.events import BarCloseEvent, BaseEvent
from data.asset_types import AssetClass
from execution.fill_simulator import FillSimulator
from execution.order_models import Account, Position, PositionStatus
from risk.risk_manager import RiskManager
from risk.risk_models import OrderSide, RiskCheckStatus
from signals.signal_engine import SignalEngine
from signals.signal_models import Signal, SignalDirection, SignalStrength


class ShadowMode:
    """Run signal+risk pipeline in parallel without sending real orders."""

    def __init__(
        self,
        signal_engine: SignalEngine,
        risk_manager: RiskManager,
        fill_simulator: FillSimulator,
        event_bus: EventBus,
        logger: BoundLogger,
        *,
        run_id: str = "shadow",
        initial_balance: float = 10000.0,
    ) -> None:
        self._signal_engine = signal_engine
        self._risk_manager = risk_manager
        self._fill_simulator = fill_simulator
        self._event_bus = event_bus
        self._logger = logger.bind(module="replay.shadow_mode")
        self._run_id = run_id
        self._metrics = MetricsCalculator()
        self._trades: list[BacktestTrade] = []
        self._open_positions: dict[str, Position] = {}
        self._equity_curve: list[tuple[datetime, float]] = []
        self._account = Account(
            account_id=f"shadow-{run_id}",
            broker="shadow",
            balance=initial_balance,
            currency="USD",
            is_paper=True,
            leverage=1.0,
            unrealized_pnl=0.0,
        )
        self._handler: Any = None
        self._running = False

    async def start(self) -> None:
        """Subscribe to BAR_CLOSE events and start accumulating shadow trades."""

        if self._running:
            return

        async def _handler(event: BaseEvent) -> None:
            if isinstance(event, BarCloseEvent):
                await self._on_bar_close(event)

        self._event_bus.subscribe(EventType.BAR_CLOSE, _handler)
        self._handler = _handler
        self._running = True

    async def stop(self) -> None:
        """Stop shadow mode subscriptions."""

        if not self._running:
            return
        if self._handler is not None:
            self._event_bus.unsubscribe(EventType.BAR_CLOSE, self._handler)
        self._handler = None
        self._running = False

    async def _on_bar_close(self, event: BarCloseEvent) -> None:
        """Process one bar in shadow mode without real order execution."""

        now = event.timestamp_close
        # Close existing positions after one bar hold.
        to_close = [item for item in self._open_positions.values() if item.symbol == event.symbol]
        for position in to_close:
            pnl = self._close_shadow_position(position, event.close, now)
            self._account = self._account.model_copy(update={"balance": self._account.balance + pnl})
            await self._risk_manager.update_on_close(position, pnl)
            self._open_positions.pop(position.position_id, None)

        decision = await self._signal_engine.analyze(
            symbol=event.symbol,
            broker=event.broker,
            timeframe=event.timeframe,
            horizon="2h",
            as_of=event.timestamp_close,
        )
        direction = decision.ensemble.final_direction
        if direction not in {SignalDirection.BUY, SignalDirection.SELL}:
            self._record_equity(now)
            return

        signal = Signal(
            strategy_id="signal_ensemble",
            strategy_version="1.0.0",
            symbol=event.symbol,
            broker=event.broker,
            timeframe=event.timeframe,
            timestamp=event.timestamp_close,
            run_id=self._run_id,
            direction=direction,
            strength=SignalStrength.NONE,
            raw_score=decision.ensemble.final_confidence * (100.0 if direction == SignalDirection.BUY else -100.0),
            confidence=decision.ensemble.final_confidence,
            reasons=decision.ensemble.all_reasons,
            regime=decision.ensemble.regime,
            horizon=decision.ensemble.horizon,
            entry_price=event.close,
            metadata={
                "asset_class": AssetClass.FOREX.value,
                "contract_size": 1.0,
                "pip_size": 0.0001,
                "strategy_id": "signal_ensemble",
                "signal_confidence": decision.ensemble.final_confidence,
                "regime_trend": decision.ensemble.regime.trend.value,
                "regime_volatility": decision.ensemble.regime.volatility.value,
                "timeframe": event.timeframe,
            },
        )
        open_positions = [position for position in self._open_positions.values() if position.status == PositionStatus.OPEN]
        risk_check = await self._risk_manager.evaluate(
            signal=signal,
            account=self._account,
            open_positions=open_positions,
            current_atr=max(event.close * 0.001, 1e-9),
        )
        if risk_check.status not in {RiskCheckStatus.APPROVED, RiskCheckStatus.MODIFIED}:
            self._record_equity(now)
            return

        quantity = float(risk_check.approved_size or 0.0)
        if quantity <= 0.0:
            self._record_equity(now)
            return
        side = OrderSide.BUY if direction == SignalDirection.BUY else OrderSide.SELL
        position = Position(
            symbol=event.symbol,
            broker=event.broker,
            side=side,
            quantity=quantity,
            entry_price=event.close,
            current_price=event.close,
            stop_loss=risk_check.suggested_sl,
            take_profit=risk_check.suggested_tp,
            trailing_stop_price=risk_check.suggested_trailing,
            status=PositionStatus.OPEN,
            opened_at=event.timestamp_close,
            signal_id=signal.signal_id,
            strategy_id=signal.strategy_id,
            asset_class=AssetClass.FOREX,
            is_paper=True,
            metadata=signal.metadata,
        )
        self._open_positions[position.position_id] = position
        self._record_equity(now)

    def get_shadow_trades(self) -> list[BacktestTrade]:
        """Return accumulated shadow trades."""

        return list(self._trades)

    def get_shadow_metrics(self) -> BacktestMetrics:
        """Compute metrics for currently accumulated shadow trades."""

        if not self._equity_curve:
            return BacktestMetrics()
        initial = self._equity_curve[0][1] if self._equity_curve else 10000.0
        return self._metrics.calculate(self._trades, self._equity_curve, initial_capital=initial)

    def compare_with_live(self, live_trades: list[Any]) -> dict[str, Any]:
        """Compare shadow trades against live trades and compute agreement rate."""

        live_keys = set()
        for trade in live_trades:
            if hasattr(trade, "symbol") and hasattr(trade, "entry_time"):
                side_value = str(getattr(trade, "side", ""))
                live_keys.add((str(trade.symbol), str(trade.entry_time), side_value))
            elif isinstance(trade, dict):
                live_keys.add((str(trade.get("symbol", "")), str(trade.get("entry_time", "")), str(trade.get("side", ""))))

        shadow_keys = {(trade.symbol, str(trade.entry_time), trade.side.value) for trade in self._trades}
        common = shadow_keys.intersection(live_keys)
        divergences = sorted(list(shadow_keys.symmetric_difference(live_keys)))
        agreement_rate = (len(common) / len(shadow_keys)) if shadow_keys else 0.0
        return {
            "divergences": divergences,
            "agreement_rate": agreement_rate,
            "shadow_trades": len(shadow_keys),
            "live_trades": len(live_keys),
        }

    def _close_shadow_position(self, position: Position, exit_price: float, when: datetime) -> float:
        pnl_per_unit = (
            exit_price - position.entry_price
            if position.side == OrderSide.BUY
            else position.entry_price - exit_price
        )
        pnl = pnl_per_unit * position.quantity
        trade = BacktestTrade(
            trade_id=position.position_id,
            symbol=position.symbol,
            strategy_id=position.strategy_id,
            side=position.side,
            entry_time=position.opened_at.astimezone(UTC),
            exit_time=when.astimezone(UTC),
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            pnl=pnl,
            pnl_net=pnl,
            commission=0.0,
            slippage=0.0,
            bars_held=1,
            exit_reason="shadow_one_bar",
            r_multiple=None,
            regime_at_entry=str(position.metadata.get("regime_trend", "unknown")),
            volatility_at_entry=str(position.metadata.get("regime_volatility", "unknown")),
            signal_confidence=float(position.metadata.get("signal_confidence", 0.0)),
            max_favorable_excursion=max(pnl, 0.0),
            max_adverse_excursion=min(pnl, 0.0),
        )
        self._trades.append(trade)
        return pnl

    def _record_equity(self, timestamp: datetime) -> None:
        equity = float(self._account.equity or self._account.balance)
        self._equity_curve.append((timestamp.astimezone(UTC), equity))


__all__ = ["ShadowMode"]
