"""CLI for running module 5 backtests."""

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
from backtest.report_generator import ReportGenerator
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run backtests for strategies")
    parser.add_argument("--strategy", type=str, default="trend_following")
    parser.add_argument("--symbol", type=str, default="EURUSD")
    parser.add_argument("--broker", type=str, default="mock_dev")
    parser.add_argument("--timeframe", type=str, default="H1")
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    parser.add_argument("--mode", type=str, default="simple", choices=["simple", "walk_forward", "out_of_sample"])
    parser.add_argument("--all-strategies", action="store_true")
    parser.add_argument("--initial-capital", type=float, default=None)
    parser.add_argument("--data-store", type=str, default="data_store/backtest")
    return parser.parse_args()


def _parse_dt(raw: str) -> datetime:
    return datetime.fromisoformat(raw).replace(tzinfo=UTC)


async def _run() -> int:
    args = _parse_args()
    module_cfg = load_backtest_config()
    run_id = f"run-backtest-{int(datetime.now(UTC).timestamp())}"
    configure_logging(run_id=run_id, environment="development", log_level="INFO")
    log = get_logger("scripts.run_backtest")
    console = Console()

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)
    mode = BacktestMode(args.mode)
    strategies = (
        [
            "trend_following",
            "mean_reversion",
            "momentum_breakout",
            "scalping_reversal",
            "swing_composite",
            "investment_fundamental",
            "range_scalp",
        ]
        if args.all_strategies
        else [args.strategy]
    )
    initial_capital = args.initial_capital or module_cfg.backtest.default_initial_capital
    config = BacktestConfig(
        run_id=run_id,
        strategy_ids=strategies,
        symbols=[args.symbol],
        brokers=[args.broker],
        timeframes=[args.timeframe],
        asset_classes=[AssetClass.FOREX if args.symbol.endswith("USD") else AssetClass.UNKNOWN],
        start_date=start,
        end_date=end,
        mode=mode,
        initial_capital=initial_capital,
        currency=module_cfg.backtest.default_currency,
        use_realistic_fills=module_cfg.backtest.use_realistic_fills,
        warmup_bars=module_cfg.backtest.warmup_bars,
        wf_train_periods=module_cfg.backtest.walk_forward.train_periods,
        wf_test_periods=module_cfg.backtest.walk_forward.test_periods,
        wf_step_periods=module_cfg.backtest.walk_forward.step_periods,
        oos_pct=module_cfg.backtest.out_of_sample.oos_pct,
        purge_bars=module_cfg.backtest.out_of_sample.purge_bars,
    )

    data_store = Path(args.data_store)
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=data_store)
    try:
        bars = await repository.get_ohlcv(
            symbol=args.symbol,
            broker=args.broker,
            timeframe=args.timeframe,
            start=start,
            end=end,
            auto_fetch=False,
        )
        if not bars:
            generated = generate_synthetic_bars(
                symbol=args.symbol,
                broker=args.broker,
                timeframe=args.timeframe,
                start=start,
                end=end,
                seed=module_cfg.backtest.random_seed,
            )
            await repository.save_ohlcv(generated)
            bars = generated
        log.info("backtest_bars_ready", bars=len(bars), symbol=args.symbol, timeframe=args.timeframe)

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
        result = await engine.run()

        output_dir = Path(module_cfg.backtest.report.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"backtest_{strategies[0]}_{args.symbol}_{args.timeframe}_{end.strftime('%Y%m%d')}"
        report = ReportGenerator(template_dir=Path("backtest/templates"))
        html_path = report.generate_html(result, output_dir / f"{base_name}.html")
        pdf_path = report.generate_pdf(result, output_dir / f"{base_name}.pdf")

        table = Table(title="Backtest Result")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Total trades", str(result.metrics.total_trades))
        table.add_row("Win rate", f"{result.metrics.win_rate * 100:.2f}%")
        table.add_row("Profit factor", f"{result.metrics.profit_factor:.3f}")
        table.add_row("Sharpe ratio", f"{result.metrics.sharpe_ratio:.3f}")
        table.add_row("Max drawdown", f"{result.metrics.max_drawdown_pct:.2f}%")
        table.add_row("Total pnl net", f"{result.metrics.total_pnl_net:.2f}")
        console.print(table)
        console.print(f"HTML report: {html_path}")
        console.print(f"PDF report: {pdf_path}")

        th = module_cfg.backtest.viability_thresholds
        viable = (
            result.metrics.profit_factor >= th.min_profit_factor
            and result.metrics.sharpe_ratio >= th.min_sharpe_ratio
            and result.metrics.max_drawdown_pct <= th.max_drawdown_pct
            and result.metrics.win_rate >= th.min_win_rate
            and result.metrics.total_trades >= th.min_trades
        )
        console.print("Verdict: PASS" if viable else "Verdict: FAIL")
        return 0 if viable else 1
    finally:
        await event_bus.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
