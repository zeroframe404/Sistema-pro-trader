"""Entry point for Auto Trading Pro module 0."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from pathlib import Path

from core.config_loader import load_config
from core.event_bus import EventBus
from core.events import SystemStartEvent, SystemStopEvent
from core.logger import configure_logging, get_logger
from core.plugin_manager import discover_strategies, load_strategy
from core.snapshot_manager import SnapshotManager
from core.strategy_registry import StrategyRegistry


async def run() -> int:
    """Load core services, start lifecycle, and wait for shutdown signal."""

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

    log.info("system_started", run_id=run_id, active_strategies=len(strategies))

    try:
        await shutdown_event.wait()
    finally:
        log.info("shutdown_started")
        await event_bus.publish(
            SystemStopEvent(
                source="main",
                run_id=run_id,
                reason="signal_received",
            )
        )

        for strategy in strategies:
            await strategy.stop()
            registry.unregister(strategy.config.strategy_id)

        snapshot_state = {
            "open_positions": [],
            "pending_orders": [],
            "equity": None,
            "strategies": registry.list_all(),
            "event_bus_metrics": event_bus.get_metrics().__dict__,
        }
        snapshot_manager.save_snapshot(snapshot_state)

        await event_bus.stop()
        log.info("system_stopped")

    return 0


def _install_signal_handlers(handler: Callable[[], None]) -> None:
    """Install SIGINT/SIGTERM handlers for cross-platform graceful shutdown."""

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handler)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: handler())


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
