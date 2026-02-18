from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backtest.backtest_models import BacktestConfig, BacktestMetrics, BacktestMode
from backtest.optimizer import StrategyOptimizer
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass


class _EngineStub:
    async def run_single_strategy(self, strategy_id, params, start, end):  # type: ignore[no-untyped-def]
        _ = (strategy_id, start, end)
        x = float(params.get("x", 0.0))
        sharpe = 5.0 - ((x - 5.0) ** 2)
        return BacktestMetrics(
            sharpe_ratio=sharpe,
            total_trades=100,
            profit_factor=max(1.0 + sharpe / 10.0, 0.1),
            monthly_returns={"2024-01": sharpe / 100.0, "2024-02": sharpe / 120.0},
            stability_score=0.7 if sharpe > 0 else 0.2,
        )


def _config() -> BacktestConfig:
    return BacktestConfig(
        strategy_ids=["trend_following"],
        symbols=["EURUSD"],
        brokers=["mock_dev"],
        timeframes=["H1"],
        asset_classes=[AssetClass.FOREX],
        start_date=datetime(2024, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 2, 1, tzinfo=UTC),
        mode=BacktestMode.SIMPLE,
    )


@pytest.mark.asyncio
async def test_penalty_increases_with_more_params() -> None:
    configure_logging(run_id="run-test-opt", environment="development", log_level="INFO")
    optimizer = StrategyOptimizer(_EngineStub(), _config(), get_logger("test.optimizer"))
    metrics = BacktestMetrics(sharpe_ratio=1.5, monthly_returns={"2024-01": 0.1})
    few = optimizer._penalty_score(metrics, {"a": 1})
    many = optimizer._penalty_score(metrics, {"a": 1, "b": 2, "c": 3, "d": 4})
    assert many < few


@pytest.mark.asyncio
async def test_optimizer_converges_on_synthetic_objective() -> None:
    configure_logging(run_id="run-test-opt-2", environment="development", log_level="INFO")
    optimizer = StrategyOptimizer(_EngineStub(), _config(), get_logger("test.optimizer"))
    result = await optimizer.optimize(
        strategy_id="trend_following",
        param_space={"x": (0.0, 10.0, 1.0)},
        n_trials=80,
    )
    assert abs(result.best_params["x"] - 5.0) <= 1.0
    assert result.best_score > 0.0


@pytest.mark.asyncio
async def test_overfitting_risk_high_for_weak_metrics() -> None:
    configure_logging(run_id="run-test-opt-3", environment="development", log_level="INFO")
    optimizer = StrategyOptimizer(_EngineStub(), _config(), get_logger("test.optimizer"))
    risk = optimizer._overfitting_risk(BacktestMetrics(sharpe_ratio=0.1, stability_score=0.1))
    assert risk == "high"


@pytest.mark.asyncio
async def test_param_importance_sums_to_one() -> None:
    configure_logging(run_id="run-test-opt-4", environment="development", log_level="INFO")
    optimizer = StrategyOptimizer(_EngineStub(), _config(), get_logger("test.optimizer"))
    result = await optimizer.optimize(
        strategy_id="trend_following",
        param_space={"x": (0.0, 10.0, 1.0), "y": (1.0, 5.0, 1.0)},
        n_trials=30,
    )
    total = sum(result.param_importance.values())
    assert total == pytest.approx(1.0, rel=1e-6)


@pytest.mark.asyncio
async def test_n_trials_one_returns_valid_result() -> None:
    configure_logging(run_id="run-test-opt-5", environment="development", log_level="INFO")
    optimizer = StrategyOptimizer(_EngineStub(), _config(), get_logger("test.optimizer"))
    result = await optimizer.optimize(
        strategy_id="trend_following",
        param_space={"x": (0.0, 10.0, 1.0)},
        n_trials=1,
    )
    assert result.n_trials == 1
    assert result.n_successful_trials == 1
