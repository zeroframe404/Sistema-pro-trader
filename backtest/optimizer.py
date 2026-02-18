"""Parameter optimization utilities for module 5."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any

from structlog.stdlib import BoundLogger

from backtest.backtest_engine import BacktestEngine
from backtest.backtest_models import BacktestConfig, BacktestMetrics, OptimizationResult


@dataclass(slots=True)
class _TrialRecord:
    params: dict[str, float]
    raw_metric: float
    score: float
    metrics: BacktestMetrics


class StrategyOptimizer:
    """Optimize strategy parameters with anti-overfit penalties."""

    def __init__(self, engine: BacktestEngine, config: BacktestConfig, logger: BoundLogger) -> None:
        self._engine = engine
        self._config = config
        self._logger = logger.bind(module="backtest.optimizer")

    async def optimize(
        self,
        strategy_id: str,
        param_space: dict[str, tuple[float, float, float]],
        n_trials: int = 100,
        metric: str = "sharpe_ratio",
        direction: str = "maximize",
        n_jobs: int = 1,
    ) -> OptimizationResult:
        """Run optimization and return ranked result."""

        _ = n_jobs
        started = time.perf_counter()
        rng = random.Random(42)
        trials: list[_TrialRecord] = []
        best: _TrialRecord | None = None

        if n_trials <= 0:
            n_trials = 1

        for trial_idx in range(n_trials):
            params = self._sample_params(param_space, rng)
            metrics = await self._engine.run_single_strategy(
                strategy_id=strategy_id,
                params=params,
                start=self._config.start_date,
                end=self._config.end_date,
            )
            raw = float(getattr(metrics, metric, 0.0))
            score = self._penalty_score(metrics, params)
            if direction.lower() == "minimize":
                score = -score
            trial = _TrialRecord(params=params, raw_metric=raw, score=score, metrics=metrics)
            trials.append(trial)
            if best is None:
                best = trial
            else:
                if score > best.score:
                    best = trial
            self._logger.info(
                "optimization_trial",
                trial=trial_idx + 1,
                n_trials=n_trials,
                score=score,
                metric=raw,
            )

        if best is None:
            best = _TrialRecord(params={}, raw_metric=0.0, score=0.0, metrics=BacktestMetrics())
        importance = self._param_importance(trials, param_space)
        risk = self._overfitting_risk(best.metrics)
        verdict = "use_params" if best.metrics.profit_factor >= 1.0 else "use_defaults"
        if best.metrics.total_trades < 10:
            verdict = "strategy_not_viable"
        return OptimizationResult(
            strategy_id=strategy_id,
            best_params={key: float(value) for key, value in best.params.items()},
            best_score=best.score,
            best_metrics=best.metrics,
            n_trials=n_trials,
            n_successful_trials=len(trials),
            optimization_time_seconds=time.perf_counter() - started,
            param_importance=importance,
            all_trials=[
                {"params": trial.params, "raw_metric": trial.raw_metric, "score": trial.score}
                for trial in trials
            ],
            overfitting_risk=risk,
            verdict=verdict,
        )

    def _objective(self, trial: Any, strategy_id: str) -> float:
        """Optuna-compatible objective placeholder."""

        _ = (trial, strategy_id)
        raise RuntimeError("Direct Optuna objective is not used in fallback optimizer")

    def _penalty_score(
        self,
        metrics: BacktestMetrics,
        params: dict[str, Any],
        lambda_complexity: float = 0.05,
        mu_instability: float = 0.1,
    ) -> float:
        """Return penalized score combining sharpe, complexity, and instability."""

        complexity = math.log(max(len(params), 1))
        monthly = list(metrics.monthly_returns.values())
        instability = self._std(monthly) if monthly else 0.0
        return float(metrics.sharpe_ratio - (lambda_complexity * complexity) - (mu_instability * instability))

    def _sample_params(
        self,
        param_space: dict[str, tuple[float, float, float]],
        rng: random.Random,
    ) -> dict[str, float]:
        params: dict[str, float] = {}
        for name, bounds in param_space.items():
            low, high, step = bounds
            if step <= 0:
                params[name] = float(low)
                continue
            if high < low:
                low, high = high, low
            values_count = int(round((high - low) / step))
            candidates = [low + step * idx for idx in range(values_count + 1)]
            params[name] = float(rng.choice(candidates))
        return params

    def _param_importance(
        self,
        trials: list[_TrialRecord],
        param_space: dict[str, tuple[float, float, float]],
    ) -> dict[str, float]:
        if not trials or not param_space:
            return {}
        scores = [trial.score for trial in trials]
        score_std = self._std(scores)
        raw: dict[str, float] = {}
        for name in param_space:
            values = [float(trial.params.get(name, 0.0)) for trial in trials]
            cov = self._cov(values, scores)
            value_std = self._std(values)
            corr = 0.0
            if value_std > 1e-12 and score_std > 1e-12:
                corr = abs(cov / (value_std * score_std))
            raw[name] = corr
        total = sum(raw.values())
        if total <= 1e-12:
            equal = 1.0 / len(raw)
            return {name: equal for name in raw}
        return {name: value / total for name, value in raw.items()}

    def _overfitting_risk(self, metrics: BacktestMetrics) -> str:
        if metrics.sharpe_ratio >= 1.0 and metrics.stability_score >= 0.6:
            return "low"
        if metrics.sharpe_ratio >= 0.5 and metrics.stability_score >= 0.3:
            return "medium"
        return "high"

    def _std(self, values: list[float]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return float(variance ** 0.5)

    def _cov(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        mean_a = sum(a) / len(a)
        mean_b = sum(b) / len(b)
        return sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=False)) / len(a)


__all__ = ["StrategyOptimizer"]
