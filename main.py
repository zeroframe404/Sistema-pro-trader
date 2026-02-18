"""Entry point for Auto Trading Pro core + data layer runtime."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import signal
from collections.abc import Callable
from pathlib import Path

from core.config_loader import load_config
from core.event_bus import EventBus
from core.event_types import EventType
from core.events import BarCloseEvent, BaseEvent, SystemStartEvent, SystemStopEvent
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
from data.normalizer import Normalizer
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector


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

        snapshot_state = {
            "open_positions": [],
            "pending_orders": [],
            "equity": None,
            "strategies": registry.list_all(),
            "event_bus_metrics": dataclasses.asdict(event_bus.get_metrics()),
            "data_layer_enabled": feed_manager is not None,
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


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(asyncio.run(run(smoke_seconds=args.smoke_seconds)))
