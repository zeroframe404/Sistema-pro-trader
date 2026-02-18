from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from backtest.backtest_engine import BacktestEngine
from backtest.backtest_models import BacktestConfig, BacktestMode, BacktestTrade
from backtest.runtime import build_backtest_runtime, generate_synthetic_bars
from data.asset_types import AssetClass
from risk.risk_models import OrderSide


def make_trade(
    *,
    idx: int = 0,
    pnl_net: float = 10.0,
    confidence: float = 0.7,
    regime: str = "ranging",
) -> BacktestTrade:
    base = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=idx)
    return BacktestTrade(
        trade_id=f"trade-{idx}",
        symbol="EURUSD",
        strategy_id="trend_following",
        side=OrderSide.BUY,
        entry_time=base,
        exit_time=base + timedelta(hours=1),
        entry_price=1.1,
        exit_price=1.101,
        quantity=1.0,
        pnl=pnl_net,
        pnl_net=pnl_net,
        commission=0.0,
        slippage=0.0,
        bars_held=1,
        exit_reason="tp",
        stop_loss=1.099,
        regime_at_entry=regime,
        volatility_at_entry="medium",
        signal_confidence=confidence,
        max_favorable_excursion=max(pnl_net, 0.0),
        max_adverse_excursion=min(pnl_net, 0.0),
    )


def make_equity_curve(start: float = 10000.0, steps: list[float] | None = None) -> list[tuple[datetime, float]]:
    steps = steps or [10.0, -5.0, 20.0, -3.0]
    current = start
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    curve: list[tuple[datetime, float]] = [(ts, current)]
    for idx, step in enumerate(steps, start=1):
        current += step
        curve.append((ts + timedelta(days=idx), current))
    return curve


async def make_backtest_engine(tmp_path: Path) -> tuple[BacktestEngine, any]:
    run_id = f"test-m5-{tmp_path.name}"
    (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    ) = await build_backtest_runtime(run_id=run_id, data_store_path=tmp_path)

    start = datetime(2023, 1, 1, tzinfo=UTC)
    end = datetime(2023, 2, 1, tzinfo=UTC)
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
        warmup_bars=30,
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
        logger=__import__("core.logger", fromlist=["get_logger"]).get_logger("tests.backtest_engine"),
    )
    return engine, event_bus
