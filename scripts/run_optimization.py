"""CLI for strategy parameter optimization in module 5."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table

from backtest.backtest_engine import BacktestEngine
from backtest.backtest_models import BacktestConfig, BacktestMode
from backtest.config_loader import load_backtest_config
from backtest.optimizer import StrategyOptimizer
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.config_loader import load_config, save_config
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize strategy parameters")
    parser.add_argument("--strategy", type=str, required=True)
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--broker", type=str, default="mock_dev")
    parser.add_argument("--timeframe", type=str, default="H1")
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    parser.add_argument("--params", type=str, required=True)
    parser.add_argument("--n-trials", type=int, default=25)
    parser.add_argument("--metric", type=str, default="sharpe_ratio")
    parser.add_argument("--apply", action="store_true", help="Persist best params to config/strategies.yaml")
    parser.add_argument("--data-store", type=str, default="data_store/backtest")
    return parser.parse_args()


def _parse_dt(raw: str) -> datetime:
    return datetime.fromisoformat(raw).replace(tzinfo=UTC)


def _parse_params(raw: str) -> dict[str, tuple[float, float, float]]:
    result: dict[str, tuple[float, float, float]] = {}
    if not raw.strip():
        return result
    chunks = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    for chunk in chunks:
        name, value = chunk.split("=", 1)
        low_s, high_s, step_s = value.split(":")
        result[name.strip()] = (float(low_s), float(high_s), float(step_s))
    return result


async def _run() -> int:
    args = _parse_args()
    cfg = load_backtest_config()
    param_space = _parse_params(args.params)
    run_id = f"run-optimization-{int(datetime.now(UTC).timestamp())}"
    configure_logging(run_id=run_id, environment="development", log_level="INFO")
    console = Console()
    log = get_logger("scripts.run_optimization")

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)
    config = BacktestConfig(
        run_id=run_id,
        strategy_ids=[args.strategy],
        symbols=[args.symbol],
        brokers=[args.broker],
        timeframes=[args.timeframe],
        asset_classes=[AssetClass.FOREX if args.symbol.endswith("USD") else AssetClass.UNKNOWN],
        start_date=start,
        end_date=end,
        mode=BacktestMode.SIMPLE,
        initial_capital=cfg.backtest.default_initial_capital,
        warmup_bars=cfg.backtest.warmup_bars,
        use_realistic_fills=cfg.backtest.use_realistic_fills,
    )
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=Path(args.data_store))
    try:
        existing = await repository.get_ohlcv(
            symbol=args.symbol,
            broker=args.broker,
            timeframe=args.timeframe,
            start=start,
            end=end,
            auto_fetch=False,
        )
        if not existing:
            generated = generate_synthetic_bars(
                symbol=args.symbol,
                broker=args.broker,
                timeframe=args.timeframe,
                start=start,
                end=end,
                seed=cfg.backtest.random_seed,
            )
            await repository.save_ohlcv(generated)

        engine = BacktestEngine(
            config=config,
            data_repository=repository,
            signal_engine=signal_engine,
            risk_manager=risk_manager,
            indicator_engine=indicator_engine,
            regime_detector=regime_detector,
            event_bus=event_bus,
            order_manager=order_manager,
            logger=get_logger("backtest.engine"),
        )
        optimizer = StrategyOptimizer(engine, config, get_logger("backtest.optimizer"))
        result = await optimizer.optimize(
            strategy_id=args.strategy,
            param_space=param_space,
            n_trials=max(args.n_trials, 1),
            metric=args.metric,
        )

        table = Table(title="Optimization Result")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("Strategy", result.strategy_id)
        table.add_row("Best score", f"{result.best_score:.4f}")
        table.add_row("Trials", str(result.n_trials))
        table.add_row("Overfitting risk", result.overfitting_risk.upper())
        table.add_row("Verdict", result.verdict)
        table.add_row("Best params", str(result.best_params))
        console.print(table)

        if args.apply:
            root_cfg = load_config(Path("config"))
            for strategy in root_cfg.strategies:
                if strategy.strategy_id != args.strategy:
                    continue
                merged = dict(strategy.parameters)
                for key, value in result.best_params.items():
                    merged[key] = int(value) if abs(value - int(value)) < 1e-9 else float(value)
                strategy.parameters = merged
                save_config(root_cfg, Path("config"))
                console.print("Applied best params to config/strategies.yaml")
                break
        log.info("optimization_finished", best_score=result.best_score)
        return 0
    finally:
        await event_bus.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
