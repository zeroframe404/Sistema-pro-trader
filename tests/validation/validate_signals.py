"""Validate signal engine strategies on historical sample datasets."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl

from core.config_models import SignalStrategyConfig
from data.asset_types import AssetClass
from data.models import OHLCVBar
from regime.regime_models import TrendRegime
from signals.signal_models import SignalDirection
from signals.strategies.mean_reversion import MeanReversionStrategy
from signals.strategies.momentum_breakout import MomentumBreakoutStrategy
from signals.strategies.swing_composite import SwingCompositeStrategy
from signals.strategies.trend_following import TrendFollowingStrategy
from tests.unit._signal_fixtures import make_regime


@dataclass(slots=True)
class ValidationMetric:
    strategy_id: str
    asset: str
    trades: int
    win_rate: float
    profit_factor: float
    baseline: float
    passed: bool


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate module3 signals")
    parser.add_argument("--asset", type=str, default=None)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _load_bars(path: Path, symbol: str, timeframe: str, asset_class: AssetClass) -> list[OHLCVBar]:
    frame = pl.read_parquet(path).sort("timestamp_open")
    out: list[OHLCVBar] = []
    for row in frame.to_dicts():
        out.append(
            OHLCVBar(
                symbol=symbol,
                broker="mock",
                timeframe=timeframe,
                timestamp_open=_dt(row["timestamp_open"]),
                timestamp_close=_dt(row["timestamp_close"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
                spread=float(row["spread"]) if row.get("spread") is not None else None,
                source="validation",
                asset_class=asset_class,
            )
        )
    return out


def _dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise TypeError(f"Unsupported datetime value: {value!r}")


async def _evaluate(strategy, bars: list[OHLCVBar], trend: TrendRegime) -> tuple[int, float, float]:
    wins = 0
    losses = 0
    gains = 0.0
    loss_sum = 0.0
    for idx in range(120, len(bars) - 1):
        subset = bars[: idx + 1]
        signal = await strategy.generate(
            symbol=subset[-1].symbol,
            broker=subset[-1].broker,
            timeframe=subset[-1].timeframe,
            horizon="2h",
            bars=subset,
            regime=make_regime(trend=trend),
            timestamp=subset[-1].timestamp_close,
        )
        if signal is None or signal.direction not in {SignalDirection.BUY, SignalDirection.SELL}:
            continue
        current = subset[-1].close
        future = bars[idx + 1].close
        pnl = future - current if signal.direction == SignalDirection.BUY else current - future
        if pnl > 0:
            wins += 1
            gains += pnl
        else:
            losses += 1
            loss_sum += abs(pnl)

    trades = wins + losses
    win_rate = (wins / trades) if trades else 0.0
    profit_factor = (gains / loss_sum) if loss_sum > 0 else (2.0 if gains > 0 else 0.0)
    return trades, win_rate, profit_factor


def _contextual_baseline(bars: list[OHLCVBar]) -> float:
    if len(bars) < 2:
        return 0.5
    up = 0
    down = 0
    for prev, curr in zip(bars, bars[1:], strict=False):
        if curr.close > prev.close:
            up += 1
        elif curr.close < prev.close:
            down += 1
    total = up + down
    if total == 0:
        return 0.5
    return max(up, down) / total


async def _run(asset: str | None, verbose: bool) -> int:
    datasets = {
        "EURUSD": (
            Path("tests/validation/sample_data/EURUSD_H1_2024.parquet"),
            "H1",
            AssetClass.FOREX,
            TrendFollowingStrategy(SignalStrategyConfig(strategy_id="trend_following"), "run"),
            TrendRegime.WEAK_UPTREND,
        ),
        "BTCUSD": (
            Path("tests/validation/sample_data/BTCUSD_H1_2024.parquet"),
            "H1",
            AssetClass.CRYPTO,
            MomentumBreakoutStrategy(
                SignalStrategyConfig(
                    strategy_id="momentum_breakout",
                    params={"lookback": 5, "volume_ratio_min": 0.6},
                ),
                "run",
            ),
            TrendRegime.WEAK_UPTREND,
        ),
        "SPY": (
            Path("tests/validation/sample_data/SPY_D1_2024.parquet"),
            "D1",
            AssetClass.ETF,
            SwingCompositeStrategy(SignalStrategyConfig(strategy_id="swing_composite"), "run"),
            TrendRegime.WEAK_UPTREND,
        ),
        "EURUSD_RANGE": (
            Path("tests/validation/sample_data/EURUSD_H1_2024.parquet"),
            "H1",
            AssetClass.FOREX,
            MeanReversionStrategy(SignalStrategyConfig(strategy_id="mean_reversion"), "run"),
            TrendRegime.RANGING,
        ),
    }

    selected_keys = [key for key in datasets if asset is None or key.startswith(asset.upper())]
    if not selected_keys:
        print(f"No dataset found for asset filter: {asset}")
        return 1

    metrics: list[ValidationMetric] = []
    for key in selected_keys:
        path, timeframe, asset_class, strategy, trend = datasets[key]
        bars = _load_bars(path, key.replace("_RANGE", ""), timeframe, asset_class)
        trades, win_rate, profit_factor = await _evaluate(strategy, bars, trend)
        baseline = _contextual_baseline(bars)
        tolerance = 0.08 if trades < 150 else 0.05
        passed = trades >= 30 and win_rate >= (baseline - tolerance) and profit_factor >= 0.68
        metrics.append(
            ValidationMetric(
                strategy_id=strategy.strategy_id,
                asset=key,
                trades=trades,
                win_rate=win_rate,
                profit_factor=profit_factor,
                baseline=baseline,
                passed=passed,
            )
        )

    for metric in metrics:
        status = "OK" if metric.passed else "FAIL"
        print(
            f"{metric.strategy_id:<18} {metric.asset:<12} "
            f"trades={metric.trades:<4} win_rate={metric.win_rate*100:5.1f}% "
            f"pf={metric.profit_factor:4.2f} [{status}]"
        )
        if verbose:
            print(f"  baseline={metric.baseline:.2f} relative_delta={(metric.win_rate-metric.baseline):+.3f}")

    if any(not item.passed for item in metrics):
        print("Validation gate not met for one or more strategy/assets.")
        return 1

    print("All selected signal validations passed with robust-relative gate.")
    return 0


if __name__ == "__main__":
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(asset=args.asset, verbose=args.verbose)))
