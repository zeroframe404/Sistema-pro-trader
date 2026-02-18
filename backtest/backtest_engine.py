"""Main orchestration engine for module 5 backtesting."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from structlog.stdlib import BoundLogger

from backtest.backtest_models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestMode,
    BacktestResult,
    BacktestTrade,
)
from backtest.data_injector import DataInjector, WindowedDataRepository
from backtest.metrics import MetricsCalculator
from backtest.regime_analysis import RegimeAnalyzer
from core.event_bus import EventBus
from core.event_types import EventType
from core.events import BarCloseEvent, BaseEvent, SignalEvent, TickEvent
from data.asset_types import AssetClass
from data.models import Tick
from execution.order_manager import OrderManager
from execution.order_models import PositionStatus
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from regime.regime_models import LiquidityRegime, MarketRegime, TrendRegime, VolatilityRegime
from risk.risk_manager import RiskManager
from signals.signal_engine import SignalEngine
from signals.signal_models import Signal, SignalDirection, SignalReason, SignalStrength
from storage.data_repository import DataRepository


class BacktestEngine:
    """Event-driven backtesting engine reusing production signal/risk/oms pipeline."""

    def __init__(
        self,
        config: BacktestConfig,
        data_repository: DataRepository,
        signal_engine: SignalEngine,
        risk_manager: RiskManager,
        indicator_engine: IndicatorEngine,
        regime_detector: RegimeDetector,
        event_bus: EventBus,
        order_manager: OrderManager,
        logger: BoundLogger,
    ) -> None:
        self.config = config
        self._base_repository = data_repository
        self._windowed_repository = WindowedDataRepository(data_repository)
        self._signal_engine = signal_engine
        self._risk_manager = risk_manager
        self._indicator_engine = indicator_engine
        self._regime_detector = regime_detector
        self._event_bus = event_bus
        self._order_manager = order_manager
        self._logger = logger.bind(module="backtest.engine")
        self._metrics = MetricsCalculator()
        self._regime_analysis = RegimeAnalyzer()
        self._latest_ticks: dict[str, Tick] = {}
        self._handlers: list[tuple[EventType, Any]] = []
        self._equity_curve: list[tuple[datetime, float]] = []
        self._drawdown_curve: list[tuple[datetime, float]] = []
        self._peak_equity = config.initial_capital
        self._symbol_context: tuple[str, str, str] | None = None

    async def run(self) -> BacktestResult:
        """Execute configured mode and return normalized result."""

        if self.config.mode == BacktestMode.SIMPLE:
            return await self._run_simple()
        if self.config.mode == BacktestMode.WALK_FORWARD:
            return await self._run_walk_forward()
        if self.config.mode == BacktestMode.OUT_OF_SAMPLE:
            return await self._run_out_of_sample()
        raise ValueError(f"Unsupported mode: {self.config.mode}")

    async def _run_simple(self) -> BacktestResult:
        started_at = time.perf_counter()
        self._reset_state(self.config.initial_capital)
        await self._attach_runtime_handlers()
        injector = DataInjector(
            event_bus=self._event_bus,
            data_repository=self._windowed_repository,
            speed_multiplier=float("inf"),
            run_id=self.config.run_id,
        )

        try:
            for symbol in self.config.symbols:
                for broker in self.config.brokers:
                    for timeframe in self.config.timeframes:
                        self._symbol_context = (symbol, broker, timeframe)
                        async for _event in injector.inject_bars(
                            symbol=symbol,
                            broker=broker,
                            timeframe=timeframe,
                            start=self.config.start_date,
                            end=self.config.end_date,
                            warmup_bars=self.config.warmup_bars,
                        ):
                            await self._drain_bus()
                            self._record_equity_point()
            await self._drain_bus()
            await self._close_open_positions()
            await self._drain_bus()
            trades = self._collect_trades()
            metrics = self._metrics.calculate(trades, self._equity_curve, self.config.initial_capital)
            metrics_by_strategy = self._metrics_by_key(trades, key_fn=lambda item: item.strategy_id)
            metrics_by_regime = self._metrics_by_key(trades, key_fn=lambda item: item.regime_at_entry)
            metrics_by_month = self._metrics_by_key(trades, key_fn=lambda item: item.entry_time.strftime("%Y-%m"))
            analysis = self._regime_analysis.analyze(trades, self._metrics)
            metrics_by_session = {
                key: value
                for key, value in analysis.get("session", {}).items()
                if isinstance(value, BacktestMetrics)
            }
            return BacktestResult(
                config=self.config,
                metrics=metrics,
                trades=trades,
                equity_curve=list(self._equity_curve),
                drawdown_curve=list(self._drawdown_curve),
                metrics_by_strategy=metrics_by_strategy,
                metrics_by_regime=metrics_by_regime,
                metrics_by_session=metrics_by_session,
                metrics_by_month=metrics_by_month,
                computed_at=datetime.now(UTC),
                duration_seconds=time.perf_counter() - started_at,
            )
        finally:
            await self._detach_runtime_handlers()

    async def _run_walk_forward(self) -> BacktestResult:
        from backtest.walk_forward import WalkForwardAnalyzer

        started_at = time.perf_counter()
        analyzer = WalkForwardAnalyzer(self, self.config)
        windows = await analyzer.run()
        if not windows:
            return BacktestResult(
                config=self.config,
                metrics=BacktestMetrics(),
                trades=[],
                equity_curve=[],
                drawdown_curve=[],
                wf_windows=[],
                duration_seconds=time.perf_counter() - started_at,
            )
        combined_metrics = self._average_metrics([window.test_metrics for window in windows])
        return BacktestResult(
            config=self.config,
            metrics=combined_metrics,
            trades=[],
            equity_curve=[],
            drawdown_curve=[],
            wf_windows=windows,
            duration_seconds=time.perf_counter() - started_at,
        )

    async def _run_out_of_sample(self) -> BacktestResult:
        from backtest.out_of_sample import OutOfSampleValidator

        started_at = time.perf_counter()
        validator = OutOfSampleValidator(self, self.config)
        is_result, oos_result = await validator.run()
        return BacktestResult(
            config=self.config,
            metrics=oos_result.metrics,
            trades=oos_result.trades,
            equity_curve=oos_result.equity_curve,
            drawdown_curve=oos_result.drawdown_curve,
            oos_metrics=oos_result.metrics,
            is_metrics=is_result.metrics,
            duration_seconds=time.perf_counter() - started_at,
        )

    async def run_single_strategy(
        self,
        strategy_id: str,
        params: dict[str, Any],
        start: datetime,
        end: datetime,
    ) -> BacktestMetrics:
        """Lightweight run for optimizers."""

        original = self.config
        cfg = original.model_copy(
            update={
                "strategy_ids": [strategy_id],
                "start_date": start,
                "end_date": end,
                "mode": BacktestMode.SIMPLE,
            },
            deep=True,
        )
        self.config = cfg
        try:
            result = await self._run_simple()
            if params:
                # Apply deterministic mild penalty for larger parameter sets.
                penalty = 0.001 * len(params)
                result.metrics.sharpe_ratio -= penalty
            return result.metrics
        finally:
            self.config = original

    def _reset_state(self, initial_capital: float) -> None:
        self._equity_curve = []
        self._drawdown_curve = []
        self._peak_equity = initial_capital
        self._latest_ticks.clear()

        # Reset OMS memory state for multi-run modes.
        self._order_manager._orders.clear()  # type: ignore[attr-defined]
        self._order_manager._orders_by_broker_id.clear()  # type: ignore[attr-defined]
        self._order_manager._positions.clear()  # type: ignore[attr-defined]
        self._order_manager._history.clear()  # type: ignore[attr-defined]
        account = self._order_manager.get_account().model_copy(
            update={"balance": initial_capital, "unrealized_pnl": 0.0, "margin_used": 0.0}
        )
        self._order_manager._account = account  # type: ignore[attr-defined]
        adapter = self._order_manager._adapter  # type: ignore[attr-defined]
        if hasattr(adapter, "_orders"):
            adapter._orders.clear()  # type: ignore[attr-defined]
        if hasattr(adapter, "_positions"):
            adapter._positions.clear()  # type: ignore[attr-defined]
        if hasattr(adapter, "_latest_tick"):
            adapter._latest_tick.clear()  # type: ignore[attr-defined]
        if hasattr(adapter, "_account"):
            adapter._account = account  # type: ignore[attr-defined]

    def _collect_trades(self) -> list[BacktestTrade]:
        positions = self._order_manager.get_positions(include_closed=True)
        closed = [item for item in positions if item.status == PositionStatus.CLOSED]
        trades: list[BacktestTrade] = []
        for position in closed:
            entry_time = position.opened_at.astimezone(UTC)
            exit_time = (position.closed_at or position.opened_at).astimezone(UTC)
            timeframe = str(position.metadata.get("timeframe", self.config.timeframes[0] if self.config.timeframes else "H1"))
            bars_held = max(
                int(position.metadata.get("bars_held", 0)),
                int(max((exit_time - entry_time).total_seconds(), 0.0) / max(self._timeframe_seconds(timeframe), 1)),
            )
            pnl_net = float(position.realized_pnl or 0.0)
            risk_per_unit = abs(position.entry_price - float(position.stop_loss or position.entry_price))
            r_multiple = (pnl_net / (risk_per_unit * max(float(position.metadata.get("requested_quantity", 1.0)), 1e-12))) if risk_per_unit > 0 else None
            trades.append(
                BacktestTrade(
                    trade_id=position.position_id,
                    symbol=position.symbol,
                    strategy_id=position.strategy_id,
                    side=position.side,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    entry_price=position.entry_price,
                    exit_price=position.close_price or position.current_price,
                    quantity=float(position.metadata.get("requested_quantity", 1.0)),
                    pnl=pnl_net,
                    pnl_net=pnl_net,
                    commission=position.commission_total,
                    slippage=float(position.metadata.get("slippage", 0.0)),
                    bars_held=bars_held,
                    exit_reason=str(position.metadata.get("exit_reason", "unknown")),
                    r_multiple=r_multiple,
                    regime_at_entry=str(position.metadata.get("regime_trend", "unknown")),
                    volatility_at_entry=str(position.metadata.get("regime_volatility", "unknown")),
                    signal_confidence=float(position.metadata.get("signal_confidence", 0.0)),
                    max_favorable_excursion=float(position.metadata.get("mfe", 0.0)),
                    max_adverse_excursion=float(position.metadata.get("mae", 0.0)),
                )
            )
        trades.sort(key=lambda item: item.entry_time)
        return trades

    async def _attach_runtime_handlers(self) -> None:
        async def on_tick(event: BaseEvent) -> None:
            if not isinstance(event, TickEvent):
                return
            self._latest_ticks[event.symbol] = Tick(
                symbol=event.symbol,
                broker=event.broker,
                timestamp=event.timestamp.astimezone(UTC),
                bid=event.bid,
                ask=event.ask,
                last=event.last,
                volume=event.volume,
                spread=event.ask - event.bid,
                source="backtest.event_bus",
            )

        async def on_bar_close(event: BaseEvent) -> None:
            if not isinstance(event, BarCloseEvent):
                return
            await self._signal_engine.on_bar_close(event)
            open_positions = self._order_manager.get_open_positions()
            if not open_positions:
                return
            actions = await self._risk_manager.monitor_open_positions(
                open_positions=open_positions,
                current_prices={event.symbol: event.close},
                current_atrs={event.symbol: max(event.close * 0.001, 1e-9)},
            )
            for action in actions:
                position_id = str(action.get("position_id", ""))
                if not position_id:
                    continue
                if action.get("action") == "close":
                    position = next((item for item in open_positions if item.position_id == position_id), None)
                    if position is None:
                        continue
                    await self._order_manager.close_position(
                        position=position,
                        reason=str(action.get("reason", "risk_monitor")),
                    )
                elif action.get("action") == "update_trailing":
                    for position in open_positions:
                        if position.position_id == position_id:
                            position.stop_loss = float(action.get("new_sl", position.stop_loss or 0.0))

        async def on_signal(event: BaseEvent) -> None:
            if not isinstance(event, SignalEvent):
                return
            if event.direction in {"WAIT", "NO_TRADE"}:
                return
            signal = self._signal_event_to_domain(event, self._latest_ticks.get(event.symbol))
            account = self._order_manager.get_account()
            open_positions = self._order_manager.get_open_positions()
            atr = float(signal.metadata.get("atr", max((signal.entry_price or 1.0) * 0.001, 1e-9)))
            risk_check = await self._risk_manager.evaluate(
                signal=signal,
                account=account,
                open_positions=open_positions,
                current_atr=atr,
            )
            if risk_check.status.value == "rejected":
                return
            await self._order_manager.submit_from_signal(signal=signal, risk_check=risk_check, account=account)

        self._event_bus.subscribe(EventType.TICK, on_tick)
        self._event_bus.subscribe(EventType.BAR_CLOSE, on_bar_close)
        self._event_bus.subscribe(EventType.SIGNAL, on_signal)
        self._handlers = [
            (EventType.TICK, on_tick),
            (EventType.BAR_CLOSE, on_bar_close),
            (EventType.SIGNAL, on_signal),
        ]

    async def _detach_runtime_handlers(self) -> None:
        for event_type, handler in self._handlers:
            self._event_bus.unsubscribe(event_type, handler)
        self._handlers = []

    async def _close_open_positions(self) -> None:
        open_positions = self._order_manager.get_open_positions()
        for position in open_positions:
            await self._order_manager.close_position(position=position, reason="backtest_end")

    async def _drain_bus(self, max_wait_seconds: float = 0.1) -> None:
        await self._event_bus.drain(timeout_seconds=max_wait_seconds)

    def _record_equity_point(self) -> None:
        account = self._order_manager.get_account()
        ts = datetime.now(UTC)
        equity = float(account.equity or account.balance)
        self._peak_equity = max(self._peak_equity, equity)
        drawdown = ((self._peak_equity - equity) / self._peak_equity) * 100.0 if self._peak_equity > 0 else 0.0
        self._equity_curve.append((ts, equity))
        self._drawdown_curve.append((ts, drawdown))

    def _metrics_by_key(self, trades: list[BacktestTrade], key_fn: Any) -> dict[str, BacktestMetrics]:
        grouped: dict[str, list[BacktestTrade]] = defaultdict(list)
        for trade in trades:
            grouped[str(key_fn(trade))].append(trade)
        result: dict[str, BacktestMetrics] = {}
        for key, group in grouped.items():
            equity = self.config.initial_capital
            curve: list[tuple[datetime, float]] = []
            for trade in sorted(group, key=lambda item: item.exit_time):
                equity += trade.pnl_net
                curve.append((trade.exit_time, equity))
            result[key] = self._metrics.calculate(group, curve, self.config.initial_capital)
        return result

    def _average_metrics(self, values: list[BacktestMetrics]) -> BacktestMetrics:
        if not values:
            return BacktestMetrics()
        numeric_fields = BacktestMetrics.model_fields.keys()
        merged: dict[str, Any] = {}
        for field in numeric_fields:
            sample = getattr(values[0], field)
            if isinstance(sample, (int, float)):
                merged[field] = float(sum(float(getattr(item, field)) for item in values) / len(values))
            elif isinstance(sample, dict):
                merged[field] = {}
            else:
                merged[field] = sample
        # Restore int fields.
        for name in ("total_trades", "winning_trades", "losing_trades", "breakeven_trades", "max_drawdown_duration_bars", "longest_winning_streak", "longest_losing_streak"):
            merged[name] = int(round(float(merged.get(name, 0))))
        return BacktestMetrics(**merged)

    def _signal_event_to_domain(self, event: SignalEvent, latest_tick: Tick | None) -> Signal:
        reasons: list[SignalReason] = []
        for raw in event.reasons:
            if not isinstance(raw, dict):
                continue
            reasons.append(
                SignalReason(
                    factor=str(raw.get("factor", "ensemble")),
                    value=raw.get("value"),
                    contribution=float(raw.get("contribution", 0.0)),
                    weight=float(raw.get("weight", 0.1)),
                    description=str(raw.get("description", "backtest_signal")),
                    direction=str(raw.get("direction", "neutral")),
                    source=str(raw.get("source", event.strategy_id)),
                )
            )
        if not reasons:
            reasons = [
                SignalReason(
                    factor="ensemble",
                    value=event.confidence,
                    contribution=0.0,
                    weight=1.0,
                    description="signal_ensemble",
                    direction="neutral",
                    source=event.strategy_id,
                )
            ]
        direction = SignalDirection(event.direction)
        raw_score = event.confidence * 100.0
        if direction == SignalDirection.SELL:
            raw_score = -raw_score

        regime = MarketRegime(
            symbol=event.symbol,
            timeframe=event.timeframe,
            timestamp=event.timestamp,
            trend=TrendRegime.RANGING,
            volatility=VolatilityRegime.MEDIUM,
            liquidity=LiquidityRegime.LIQUID,
            is_tradeable=True,
            no_trade_reasons=[],
            confidence=0.5,
            recommended_strategies=[event.strategy_id],
            description="backtest_default_regime",
        )
        entry_price = latest_tick.last if latest_tick is not None else None
        metadata = {
            "entry_price": entry_price,
            "last_price": entry_price,
            "asset_class": AssetClass.FOREX.value,
            "strategy_id": event.strategy_id,
            "contract_size": 100000.0 if event.symbol.endswith("USD") and len(event.symbol) == 6 else 1.0,
            "pip_size": 0.0001 if event.symbol.endswith("USD") and len(event.symbol) == 6 else 0.01,
            "account_equity": float(self._order_manager.get_account().equity or 0.0),
            "signal_confidence": event.confidence,
            "regime_trend": regime.trend.value,
            "regime_volatility": regime.volatility.value,
            "timeframe": event.timeframe,
        }
        return Signal(
            signal_id=event.event_id,
            strategy_id=event.strategy_id,
            strategy_version=event.strategy_version,
            symbol=event.symbol,
            broker=event.broker,
            timeframe=event.timeframe,
            timestamp=event.timestamp,
            run_id=event.run_id,
            direction=direction,
            strength=SignalStrength.NONE,
            raw_score=raw_score,
            confidence=event.confidence,
            reasons=reasons,
            regime=regime,
            horizon=event.horizon,
            entry_price=entry_price,
            metadata=metadata,
        )

    def _timeframe_seconds(self, timeframe: str) -> int:
        mapping = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "M30": 1800,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
            "W1": 604800,
            "MN1": 2592000,
        }
        return mapping.get(timeframe.upper(), 3600)


__all__ = ["BacktestEngine"]
