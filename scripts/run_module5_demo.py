"""End-to-end demo runner for module 5."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console

from backtest.backtest_engine import BacktestEngine
from backtest.backtest_models import BacktestConfig, BacktestMode
from backtest.config_loader import load_backtest_config
from backtest.optimizer import StrategyOptimizer
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.config_models import AntiOvertradingConfig, FiltersConfig, SignalsConfig
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass
from execution.fill_simulator import FillSimulator
from replay.market_replayer import MarketReplayer
from replay.replay_controller import ReplayController
from replay.shadow_mode import ShadowMode
from risk.slippage_model import SlippageModel


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run module 5 demo scenarios")
    parser.add_argument("--scenario", type=str, default="all", help="A|B|C|D|E|F|all")
    return parser.parse_args()


def _permissive_signals_config() -> SignalsConfig:
    return SignalsConfig(
        filters=FiltersConfig(
            regime_filter=False,
            news_filter=False,
            session_filter=False,
            spread_filter=False,
            correlation_filter=False,
        ),
        anti_overtrading=AntiOvertradingConfig(enabled=False),
    )


async def _scenario_backtest(console: Console, cfg, label: str, mode: BacktestMode, strategy: str, symbol: str) -> bool:
    run_id = f"demo-{label}-{int(datetime.now(UTC).timestamp())}"
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(
        run_id=run_id,
        data_store_path=Path("data_store/demo_module5") / label.lower(),
        signals_config=_permissive_signals_config(),
    )
    start = datetime(2023, 1, 1, tzinfo=UTC)
    end = datetime(2023, 3, 1, tzinfo=UTC)
    try:
        bars = generate_synthetic_bars(
            symbol=symbol,
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            seed=cfg.backtest.random_seed,
            asset_class=AssetClass.FOREX if symbol.endswith("USD") else AssetClass.CRYPTO,
        )
        await repository.save_ohlcv(bars)
        bt_config = BacktestConfig(
            run_id=run_id,
            strategy_ids=[strategy],
            symbols=[symbol],
            brokers=["mock_dev"],
            timeframes=["H1"],
            asset_classes=[AssetClass.FOREX if symbol.endswith("USD") else AssetClass.CRYPTO],
            start_date=start,
            end_date=end,
            mode=mode,
            initial_capital=cfg.backtest.default_initial_capital,
            warmup_bars=50,
            wf_train_periods=200,
            wf_test_periods=60,
            wf_step_periods=60,
            oos_pct=0.25,
            purge_bars=5,
        )
        engine = BacktestEngine(
            config=bt_config,
            data_repository=repository,
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            indicator_engine=indicator_engine,
            regime_detector=regime_detector,
            event_bus=event_bus,
            order_manager=order_manager,
            logger=get_logger("demo.backtest_engine"),
        )
        result = await engine.run()
        if mode == BacktestMode.WALK_FORWARD:
            ok = bool(result.wf_windows) and len(result.wf_windows) >= 3
        elif mode == BacktestMode.OUT_OF_SAMPLE:
            ok = result.oos_metrics is not None and result.is_metrics is not None
        else:
            ok = result.metrics.total_trades >= 1 and result.metrics.total_pnl_net != 0.0
        console.print(f"Scenario {label}: {'PASS' if ok else 'FAIL'}")
        return ok
    finally:
        await event_bus.stop()


async def _scenario_optimizer(console: Console, cfg) -> bool:
    run_id = f"demo-D-{int(datetime.now(UTC).timestamp())}"
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=Path("data_store/demo_module5/optimizer"))
    start = datetime(2023, 1, 1, tzinfo=UTC)
    end = datetime(2023, 2, 1, tzinfo=UTC)
    try:
        bars = generate_synthetic_bars(
            symbol="SPY",
            broker="mock_dev",
            timeframe="D1",
            start=start,
            end=end,
            seed=cfg.backtest.random_seed + 7,
            asset_class=AssetClass.ETF,
            base_price=420.0,
        )
        await repository.save_ohlcv(bars)
        bt_config = BacktestConfig(
            run_id=run_id,
            strategy_ids=["trend_following"],
            symbols=["SPY"],
            brokers=["mock_dev"],
            timeframes=["D1"],
            asset_classes=[AssetClass.ETF],
            start_date=start,
            end_date=end,
            mode=BacktestMode.SIMPLE,
            initial_capital=10000.0,
            warmup_bars=10,
        )
        engine = BacktestEngine(
            config=bt_config,
            data_repository=repository,
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            indicator_engine=indicator_engine,
            regime_detector=regime_detector,
            event_bus=event_bus,
            order_manager=order_manager,
            logger=get_logger("demo.backtest_engine"),
        )
        optimizer = StrategyOptimizer(engine, bt_config, get_logger("demo.optimizer"))
        result = await optimizer.optimize(
            strategy_id="trend_following",
            param_space={"rsi_period": (7, 30, 1), "ema_fast": (5, 50, 5)},
            n_trials=25,
        )
        ok = bool(result.best_params) and result.n_trials == 25
        console.print(f"Scenario D: {'PASS' if ok else 'FAIL'}")
        return ok
    finally:
        await event_bus.stop()


async def _scenario_replay(console: Console, cfg) -> bool:
    run_id = f"demo-E-{int(datetime.now(UTC).timestamp())}"
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=Path("data_store/demo_module5/replay"))
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=100)
    try:
        bars = generate_synthetic_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            seed=cfg.backtest.random_seed + 15,
        )
        await repository.save_ohlcv(bars)
        controller = ReplayController()
        replayer = MarketReplayer(
            data_repository=repository,
            event_bus=event_bus,
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            order_manager=order_manager,
            controller=controller,
            run_id=run_id,
        )
        started = datetime.now(UTC)
        await replayer.start(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            speed=float("inf"),
        )
        elapsed = (datetime.now(UTC) - started).total_seconds()
        ok = replayer.get_current_state()["index"] >= 100 and elapsed < 5.0
        console.print(f"Scenario E: {'PASS' if ok else 'FAIL'}")
        return ok
    finally:
        await event_bus.stop()


async def _scenario_shadow(console: Console, cfg) -> bool:
    run_id = f"demo-F-{int(datetime.now(UTC).timestamp())}"
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(
        run_id=run_id,
        data_store_path=Path("data_store/demo_module5/shadow"),
        signals_config=_permissive_signals_config(),
    )
    start = datetime(2024, 2, 1, tzinfo=UTC)
    end = start + timedelta(hours=120)
    try:
        bars = generate_synthetic_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            seed=cfg.backtest.random_seed + 21,
        )
        await repository.save_ohlcv(bars)
        shadow = ShadowMode(
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            fill_simulator=FillSimulator(slippage_model=SlippageModel()),
            event_bus=event_bus,
            logger=get_logger("demo.shadow"),
            run_id=run_id,
            initial_balance=10000.0,
        )
        await shadow.start()
        controller = ReplayController()
        replayer = MarketReplayer(
            data_repository=repository,
            event_bus=event_bus,
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            order_manager=order_manager,
            controller=controller,
            run_id=run_id,
        )
        await replayer.start(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            speed=float("inf"),
        )
        await shadow.stop()
        trades = shadow.get_shadow_trades()
        ok = len(trades) >= 1 and len(order_manager.get_orders()) == 0
        console.print(f"Scenario F: {'PASS' if ok else 'FAIL'}")
        return ok
    finally:
        await event_bus.stop()


async def _main() -> int:
    args = _parse_args()
    cfg = load_backtest_config()
    configure_logging(run_id=f"run-module5-demo-{int(datetime.now(UTC).timestamp())}", environment="development", log_level="INFO")
    console = Console()
    console.print("Module 5 Demo")

    scenarios = {
        "A": lambda: _scenario_backtest(console, cfg, "A", BacktestMode.SIMPLE, "trend_following", "EURUSD"),
        "B": lambda: _scenario_backtest(console, cfg, "B", BacktestMode.WALK_FORWARD, "mean_reversion", "EURUSD"),
        "C": lambda: _scenario_backtest(console, cfg, "C", BacktestMode.OUT_OF_SAMPLE, "momentum_breakout", "BTCUSD"),
        "D": lambda: _scenario_optimizer(console, cfg),
        "E": lambda: _scenario_replay(console, cfg),
        "F": lambda: _scenario_shadow(console, cfg),
    }
    selected = [args.scenario.upper()] if args.scenario.lower() != "all" else ["A", "B", "C", "D", "E", "F"]
    failed: list[str] = []
    for item in selected:
        runner = scenarios.get(item)
        if runner is None:
            console.print(f"Unknown scenario: {item}")
            return 1
        ok = await runner()
        if not ok:
            failed.append(item)
    if failed:
        console.print(f"Failed scenarios: {failed}")
        return 1
    console.print("All scenarios PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
