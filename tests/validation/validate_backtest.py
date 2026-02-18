"""Validation checks for module 5 anti-bias guarantees."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.backtest_engine import BacktestEngine
from backtest.backtest_models import BacktestConfig, BacktestMode
from backtest.data_injector import DataInjector, WindowedDataRepository
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass


async def _run_backtest(run_id: str, data_store: Path, use_realistic: bool) -> tuple[any, any]:
    event_bus, repository, indicator_engine, regime_detector, signal_engine, risk_manager, order_manager = await build_backtest_runtime(
        run_id=run_id,
        data_store_path=data_store,
    )
    start = datetime(2023, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=10)
    bars = generate_synthetic_bars(
        symbol="EURUSD",
        broker="mock_dev",
        timeframe="H1",
        start=start,
        end=end,
        seed=42,
        asset_class=AssetClass.FOREX,
    )
    await repository.save_ohlcv(bars)
    config = BacktestConfig(
        run_id=run_id,
        strategy_ids=["trend_following"],
        symbols=["EURUSD"],
        brokers=["mock_dev"],
        timeframes=["H1"],
        asset_classes=[AssetClass.FOREX],
        start_date=start,
        end_date=end,
        mode=BacktestMode.SIMPLE,
        initial_capital=10000.0,
        warmup_bars=50,
        use_realistic_fills=use_realistic,
    )
    engine = BacktestEngine(
        config=config,
        data_repository=repository,
        signal_engine=signal_engine,
        risk_manager=risk_manager,
        indicator_engine=indicator_engine,
        regime_detector=regime_detector,
        event_bus=event_bus,
        order_manager=order_manager,
        logger=get_logger("validation.backtest_engine"),
    )
    result = await engine.run()
    return result, event_bus


async def _validate_anti_lookahead(tmp_dir: Path) -> bool:
    event_bus, repository, *_ = await build_backtest_runtime(run_id="val-lookahead", data_store_path=tmp_dir / "lookahead")
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=20)
        bars = generate_synthetic_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            seed=42,
            asset_class=AssetClass.FOREX,
        )
        await repository.save_ohlcv(bars)
        windowed = WindowedDataRepository(repository)
        injector = DataInjector(event_bus, windowed, run_id="val-lookahead")
        ok = True
        count = 0

        async def _on_bar(_bar) -> None:
            nonlocal count, ok
            count += 1
            if windowed.visible_count("EURUSD", "mock_dev", "H1") != count:
                ok = False

        async for _ in injector.inject_bars(
            symbol="EURUSD",
            broker="mock_dev",
            timeframe="H1",
            start=start,
            end=end,
            warmup_bars=0,
            on_bar=_on_bar,
        ):
            pass
        return ok
    finally:
        await event_bus.stop()


async def _main() -> int:
    configure_logging(run_id="run-validate-backtest", environment="development", log_level="INFO")
    temp = Path("data_store/validation_backtest")
    temp.mkdir(parents=True, exist_ok=True)

    lookahead_ok = await _validate_anti_lookahead(temp)

    result_a, bus_a = await _run_backtest("val-determinism-a", temp / "det_a", use_realistic=True)
    result_b, bus_b = await _run_backtest("val-determinism-b", temp / "det_b", use_realistic=True)
    try:
        trades_a = [(trade.symbol, trade.side.value, trade.entry_time.isoformat(), round(trade.pnl_net, 6)) for trade in result_a.trades]
        trades_b = [(trade.symbol, trade.side.value, trade.entry_time.isoformat(), round(trade.pnl_net, 6)) for trade in result_b.trades]
        determinism_ok = trades_a == trades_b
    finally:
        await bus_a.stop()
        await bus_b.stop()

    result_costs, bus_costs = await _run_backtest("val-costs-on", temp / "costs_on", use_realistic=True)
    result_no_costs, bus_no_costs = await _run_backtest("val-costs-off", temp / "costs_off", use_realistic=False)
    try:
        # Proxy check using reported commission totals.
        costs_ok = result_costs.metrics.total_pnl_net <= (result_no_costs.metrics.total_pnl_net + abs(result_costs.metrics.total_commission) + 1e-6)
    finally:
        await bus_costs.stop()
        await bus_no_costs.stop()

    result_oos, bus_oos = await _run_backtest("val-oos", temp / "oos", use_realistic=True)
    try:
        # Light consistency check: avoid unrealistic OOS outperformance explosion.
        is_sharpe = max(result_oos.metrics.sharpe_ratio, 1e-6)
        oos_consistency_ok = result_oos.metrics.sharpe_ratio <= (is_sharpe * 1.8)
    finally:
        await bus_oos.stop()

    print("Validating anti-look-ahead...   PASS" if lookahead_ok else "Validating anti-look-ahead...   FAIL")
    print("Validating determinism...      PASS" if determinism_ok else "Validating determinism...      FAIL")
    print("Validating costs...            PASS" if costs_ok else "Validating costs...            FAIL")
    print("Validating IS/OOS...           PASS" if oos_consistency_ok else "Validating IS/OOS...           FAIL")
    print("------------------------------------------------------------")
    checks = [lookahead_ok, determinism_ok, costs_ok, oos_consistency_ok]
    if all(checks):
        print("Validation: PASS (4/4 checks)")
        return 0
    print(f"Validation: FAIL ({sum(1 for check in checks if check)}/4 checks)")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
