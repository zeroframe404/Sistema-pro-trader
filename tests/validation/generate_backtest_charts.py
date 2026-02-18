"""Generate basic backtest validation charts for module 5."""

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
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass


async def _run() -> int:
    configure_logging(run_id="run-generate-backtest-charts", environment="development", log_level="INFO")
    out_dir = Path("tests/validation/charts")
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = "charts-module5"
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=Path("data_store/validation_charts"))
    try:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=7)
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
            warmup_bars=30,
            initial_capital=10000.0,
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
            logger=get_logger("validation.charts.engine"),
        )
        result = await engine.run()
        try:
            import matplotlib.pyplot as plt
        except Exception:  # noqa: BLE001
            print("matplotlib unavailable, skipping chart generation")
            return 0

        if result.equity_curve:
            fig, axis = plt.subplots(figsize=(9, 4))
            axis.plot([ts for ts, _ in result.equity_curve], [value for _, value in result.equity_curve])
            axis.set_title("Equity Curve")
            axis.grid(True, alpha=0.3)
            fig.savefig(out_dir / "equity_curve.png")
            plt.close(fig)

        if result.drawdown_curve:
            fig, axis = plt.subplots(figsize=(9, 4))
            axis.fill_between(
                [ts for ts, _ in result.drawdown_curve],
                [value for _, value in result.drawdown_curve],
                color="tomato",
                alpha=0.5,
            )
            axis.set_title("Drawdown Curve")
            axis.grid(True, alpha=0.3)
            fig.savefig(out_dir / "drawdown_curve.png")
            plt.close(fig)
        print(f"Charts generated in {out_dir}")
        return 0
    finally:
        await event_bus.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
