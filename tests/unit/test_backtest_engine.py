from __future__ import annotations

from pathlib import Path

import pytest

from backtest.backtest_models import BacktestMode
from tests.unit._backtest_fixtures import make_backtest_engine


@pytest.mark.asyncio
async def test_backtest_zero_trades_returns_zero_metrics(tmp_path: Path) -> None:
    engine, bus = await make_backtest_engine(tmp_path / "zero")
    try:
        engine.config.mode = BacktestMode.SIMPLE
        engine._signal_engine._config.enabled = False  # noqa: SLF001
        result = await engine.run()
        assert result.metrics.total_trades == 0
        assert result.metrics.total_pnl_net == 0.0
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_capital_consistency_equals_sum_trade_pnl(tmp_path: Path) -> None:
    engine, bus = await make_backtest_engine(tmp_path / "capital")
    try:
        result = await engine.run()
        if result.trades:
            expected = engine.config.initial_capital + sum(trade.pnl_net for trade in result.trades)
            final_equity = result.equity_curve[-1][1] if result.equity_curve else engine.config.initial_capital
            assert final_equity == pytest.approx(expected, rel=1e-3, abs=5.0)
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_each_trade_has_regime_at_entry(tmp_path: Path) -> None:
    engine, bus = await make_backtest_engine(tmp_path / "regime")
    try:
        result = await engine.run()
        assert all(trade.regime_at_entry is not None for trade in result.trades)
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_trades_are_chronological(tmp_path: Path) -> None:
    engine, bus = await make_backtest_engine(tmp_path / "chronological")
    try:
        result = await engine.run()
        assert all(
            first.entry_time <= second.entry_time
            for first, second in zip(result.trades, result.trades[1:], strict=False)
        )
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_run_walk_forward_and_oos_modes(tmp_path: Path) -> None:
    engine, bus = await make_backtest_engine(tmp_path / "modes")
    try:
        engine.config.mode = BacktestMode.WALK_FORWARD
        engine.config.wf_train_periods = 200
        engine.config.wf_test_periods = 80
        engine.config.wf_step_periods = 80
        wf_result = await engine.run()
        assert wf_result.wf_windows is not None
        engine.config.mode = BacktestMode.OUT_OF_SAMPLE
        oos_result = await engine.run()
        assert oos_result.oos_metrics is not None
        assert oos_result.is_metrics is not None
    finally:
        await bus.stop()
