"""Entry point for Auto Trading Pro core + data layer runtime."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import signal
from collections.abc import Callable
from datetime import UTC
from pathlib import Path

from core.audit_journal import AuditJournal
from core.config_loader import load_config
from core.event_bus import EventBus
from core.event_types import EventType
from core.events import (
    BarCloseEvent,
    BaseEvent,
    SignalEvent,
    SystemStartEvent,
    SystemStopEvent,
    TickEvent,
)
from core.logger import configure_logging, get_logger
from core.plugin_manager import discover_strategies, load_strategy
from core.snapshot_manager import SnapshotManager
from core.strategy_registry import StrategyRegistry
from data.connectors.crypto_connector import CryptoConnector
from data.connectors.fxpro_connector import FXProConnector
from data.connectors.iol_connector import IOLConnector
from data.connectors.iqoption_connector import IQOptionConnector
from data.connectors.mock_connector import MockConnector
from data.connectors.mt5_connector import MT5Connector
from data.connectors.ninjatrader_connector import NinjaTraderConnector
from data.connectors.tradingview_connector import TradingViewConnector
from data.feed_manager import FeedManager
from data.models import Tick
from data.normalizer import Normalizer
from execution.adapters.paper_adapter import PaperAdapter
from execution.fill_simulator import FillSimulator
from execution.idempotency import IdempotencyManager
from execution.order_manager import OrderManager
from execution.reconciler import Reconciler
from execution.retry_handler import RetryHandler
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from regime.regime_models import LiquidityRegime, MarketRegime, TrendRegime, VolatilityRegime
from risk.drawdown_tracker import DrawdownTracker
from risk.exposure_tracker import ExposureTracker
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from risk.slippage_model import SlippageModel
from risk.stop_manager import StopManager
from signals.signal_engine import SignalEngine
from signals.signal_models import Signal, SignalDirection, SignalReason, SignalStrength


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Auto Trading Pro runtime")
    parser.add_argument(
        "--smoke-seconds",
        type=int,
        default=None,
        help="Auto-stop runtime after N seconds for smoke validation.",
    )
    return parser.parse_args()


async def run(smoke_seconds: int | None = None) -> int:
    """Load core services, optional data layer, and wait for shutdown signal."""

    config_path = Path("config")
    config = load_config(config_path)

    run_id = config.system.run_id or "unknown"
    configure_logging(
        run_id=run_id,
        environment=config.system.environment.value,
        log_level=config.system.log_level.value,
    )
    log = get_logger("main")

    event_bus = EventBus(
        backend=config.system.event_bus_backend.value,
        redis_url=config.system.redis_url,
    )
    registry = StrategyRegistry(event_bus=event_bus, run_id=run_id)
    snapshot_manager = SnapshotManager(Path("snapshots"))

    shutdown_event = asyncio.Event()
    strategies = []
    feed_manager: FeedManager | None = None
    indicator_engine: IndicatorEngine | None = None
    regime_detector: RegimeDetector | None = None
    signal_engine: SignalEngine | None = None
    risk_manager: RiskManager | None = None
    order_manager: OrderManager | None = None
    paper_adapter: PaperAdapter | None = None
    latest_ticks: dict[str, Tick] = {}

    def _trigger_shutdown() -> None:
        shutdown_event.set()

    _install_signal_handlers(_trigger_shutdown)

    await event_bus.start()
    await event_bus.publish(
        SystemStartEvent(
            source="main",
            run_id=run_id,
            environment=config.system.environment.value,
        )
    )

    discovered = discover_strategies(Path("strategies"))
    log.info("strategies_discovered", total=len(discovered))

    for strategy_config in config.strategies:
        if not strategy_config.enabled:
            continue
        strategy = load_strategy(strategy_config.strategy_class, strategy_config, event_bus)
        await strategy.start()
        registry.register(strategy)
        strategies.append(strategy)

    connectors = _build_connectors(config=config, event_bus=event_bus, run_id=run_id)
    if connectors:
        feed_manager = FeedManager(
            connectors=connectors,
            event_bus=event_bus,
            run_id=run_id,
            data_store_path=Path(config.system.data_store_path),
            logger=get_logger("data.feed_manager"),
        )
        await feed_manager.start()
        log.info("data_layer_started", connectors=len(connectors))

        indicator_engine = IndicatorEngine(
            data_repository=feed_manager.get_repository(),
            cache_enabled=config.indicators.indicator_engine.cache_enabled,
            cache_ttl_seconds=config.indicators.indicator_engine.cache_ttl_seconds,
            max_lookback_bars=config.indicators.indicator_engine.max_lookback_bars,
            backend_preference=config.indicators.indicator_engine.backend_preference.value,
        )

        if config.indicators.regime.enabled:
            regime_detector = RegimeDetector(
                indicator_engine=indicator_engine,
                data_repository=feed_manager.get_repository(),
                event_bus=event_bus,
                config=config.indicators.regime,
                run_id=run_id,
            )

            @event_bus.subscribe(EventType.BAR_CLOSE)
            async def _on_bar_close(event: BaseEvent) -> None:
                if not isinstance(event, BarCloseEvent):
                    return
                await regime_detector.detect_on_bar_close(event)

            log.info("regime_detector_enabled")

        if config.signals.enabled and config.signals.engine.enabled:
            audit_journal = AuditJournal(
                jsonl_path=Path(config.system.data_store_path) / "audit_signals.jsonl",
            )
            signal_engine = SignalEngine(
                config=config.signals,
                indicator_engine=indicator_engine,
                regime_detector=regime_detector
                if regime_detector is not None
                else RegimeDetector(indicator_engine=indicator_engine, data_repository=feed_manager.get_repository(), run_id=run_id),
                data_repository=feed_manager.get_repository(),
                event_bus=event_bus,
                logger=get_logger("signals.engine"),
                run_id=run_id,
                audit_journal=audit_journal,
            )
            await signal_engine.start()

            @event_bus.subscribe(EventType.BAR_CLOSE)
            async def _on_signal_bar_close(event: BaseEvent) -> None:
                if not isinstance(event, BarCloseEvent):
                    return
                await signal_engine.on_bar_close(event)

            log.info("signal_engine_enabled")

        if config.risk.enabled and signal_engine is not None:
            position_sizer = PositionSizer()
            stop_manager = StopManager()
            drawdown_tracker = DrawdownTracker()
            exposure_tracker = ExposureTracker()
            kill_switch = KillSwitch(config=config.risk.kill_switch, event_bus=event_bus, run_id=run_id)
            risk_manager = RiskManager(
                config=config.risk,
                position_sizer=position_sizer,
                stop_manager=stop_manager,
                drawdown_tracker=drawdown_tracker,
                exposure_tracker=exposure_tracker,
                kill_switch=kill_switch,
                event_bus=event_bus,
                logger=get_logger("risk.manager"),
                run_id=run_id,
            )

            slippage_model = SlippageModel()
            fill_simulator = FillSimulator(slippage_model=slippage_model)
            paper_adapter = PaperAdapter(
                initial_balance=config.risk.paper.initial_balance,
                fill_simulator=fill_simulator,
                slippage_model=slippage_model,
                event_bus=event_bus,
                logger=get_logger("execution.paper_adapter"),
                run_id=run_id,
                risk_config=config.risk,
            )
            idempotency = IdempotencyManager(Path(config.system.data_store_path) / "oms.sqlite")
            reconciler = Reconciler()
            retry_handler = RetryHandler()
            order_manager = OrderManager(
                broker_adapter=paper_adapter,
                risk_manager=risk_manager,
                idempotency=idempotency,
                reconciler=reconciler,
                retry_handler=retry_handler,
                event_bus=event_bus,
                logger=get_logger("execution.order_manager"),
                db_path=Path(config.system.data_store_path) / "oms.sqlite",
                run_id=run_id,
            )
            await order_manager.start()

            @event_bus.subscribe(EventType.TICK)
            async def _on_tick_for_paper(event: BaseEvent) -> None:
                if paper_adapter is None or not isinstance(event, TickEvent):
                    return
                tick = Tick(
                    symbol=event.symbol,
                    broker=event.broker,
                    timestamp=event.timestamp.astimezone(UTC),
                    bid=event.bid,
                    ask=event.ask,
                    last=event.last,
                    volume=event.volume,
                    spread=event.ask - event.bid,
                    source="main.event_bridge",
                )
                latest_ticks[tick.symbol] = tick
                await paper_adapter.process_tick(tick)

            @event_bus.subscribe(EventType.SIGNAL)
            async def _on_signal_for_oms(event: BaseEvent) -> None:
                if risk_manager is None or order_manager is None or not isinstance(event, SignalEvent):
                    return
                if event.direction in {"WAIT", "NO_TRADE"}:
                    return

                signal = _signal_event_to_domain(event, latest_ticks.get(event.symbol))
                account = order_manager.get_account()
                open_positions = order_manager.get_open_positions()
                atr_hint = signal.metadata.get("atr")
                atr_value = float(atr_hint) if isinstance(atr_hint, (int, float)) else None
                risk_check = await risk_manager.evaluate(
                    signal=signal,
                    account=account,
                    open_positions=open_positions,
                    current_atr=atr_value,
                )
                if risk_check.status.value == "rejected":
                    log.info(
                        "risk_rejected_signal",
                        symbol=event.symbol,
                        reasons=risk_check.rejection_reasons,
                    )
                    return
                await order_manager.submit_from_signal(signal=signal, risk_check=risk_check, account=account)

            log.info("risk_oms_enabled")
    else:
        log.info("data_layer_skipped", reason="no_enabled_data_connectors")

    if smoke_seconds is not None and smoke_seconds > 0:

        async def _smoke_stop() -> None:
            await asyncio.sleep(smoke_seconds)
            shutdown_event.set()

        asyncio.create_task(_smoke_stop(), name="smoke-stop-task")

    log.info("system_started", run_id=run_id, active_strategies=len(strategies))

    try:
        await shutdown_event.wait()
    finally:
        log.info("shutdown_started")
        await event_bus.publish(
            SystemStopEvent(
                source="main",
                run_id=run_id,
                reason="signal_received_or_smoke_timeout",
            )
        )

        for strategy in strategies:
            await strategy.stop()
            registry.unregister(strategy.config.strategy_id)

        if feed_manager is not None:
            await feed_manager.stop()

        if order_manager is not None:
            try:
                sync = await order_manager.sync_with_broker()
                log.info("oms_reconcile", report=sync["report"], fixes=sync["fixes"])
            except Exception as exc:  # noqa: BLE001
                log.warning("oms_reconcile_failed", error=str(exc))

        snapshot_state = {
            "open_positions": [],
            "pending_orders": [],
            "equity": None,
            "strategies": registry.list_all(),
            "event_bus_metrics": dataclasses.asdict(event_bus.get_metrics()),
            "data_layer_enabled": feed_manager is not None,
            "active_signals": len(signal_engine.get_active_signals()) if signal_engine is not None else 0,
            "risk_enabled": risk_manager is not None,
            "oms_enabled": order_manager is not None,
            "oms_open_positions": len(order_manager.get_open_positions()) if order_manager is not None else 0,
        }
        snapshot_manager.save_snapshot(snapshot_state)

        await event_bus.stop()
        log.info("system_stopped")

    return 0


def _build_connectors(config, event_bus: EventBus, run_id: str):
    normalizer = Normalizer()
    logger = get_logger("data.connector_factory")

    connector_map = {
        "mock": MockConnector,
        "mt5": MT5Connector,
        "iqoption": IQOptionConnector,
        "iol": IOLConnector,
        "ccxt": CryptoConnector,
        "tradingview": TradingViewConnector,
        "ninjatrader": NinjaTraderConnector,
        "fxpro": FXProConnector,
    }

    connectors = []
    for broker in config.brokers:
        if not broker.enabled:
            continue

        connector_cls = connector_map.get(broker.broker_type.lower())
        if connector_cls is None:
            logger.warning("unsupported_broker_type", broker_type=broker.broker_type)
            continue

        if connector_cls is MockConnector:
            connector = connector_cls(
                config=broker,
                event_bus=event_bus,
                normalizer=normalizer,
                logger=logger,
                run_id=run_id,
                latency_ms=float(broker.extra.get("latency_ms", 10.0)),
                error_rate=float(broker.extra.get("error_rate", 0.0)),
            )
        else:
            connector = connector_cls(
                config=broker,
                event_bus=event_bus,
                normalizer=normalizer,
                logger=logger,
                run_id=run_id,
            )

        connectors.append(connector)

    return connectors


def _install_signal_handlers(handler: Callable[[], None]) -> None:
    """Install SIGINT/SIGTERM handlers for cross-platform graceful shutdown."""

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handler)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: handler())


def _signal_event_to_domain(event: SignalEvent, latest_tick: Tick | None) -> Signal:
    reasons: list[SignalReason] = []
    for raw in event.reasons:
        if not isinstance(raw, dict):
            continue
        reasons.append(
            SignalReason(
                factor=str(raw.get("factor", "signal_factor")),
                value=raw.get("value"),
                contribution=float(raw.get("contribution", 0.0)),
                weight=float(raw.get("weight", 0.1)),
                description=str(raw.get("description", "Generated by signal ensemble")),
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
                description="Signal from ensemble output",
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
        description="runtime_default_regime",
    )

    entry_price = latest_tick.last if latest_tick is not None else None
    metadata = {
        "entry_price": entry_price,
        "last_price": entry_price,
        "asset_class": "forex",
        "strategy_id": event.strategy_id,
        "contract_size": 100000.0 if event.symbol.endswith("USD") and len(event.symbol) == 6 else 1.0,
        "pip_size": 0.0001 if event.symbol.endswith("USD") and len(event.symbol) == 6 else 0.01,
        "account_equity": 0.0,
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


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(asyncio.run(run(smoke_seconds=args.smoke_seconds)))
