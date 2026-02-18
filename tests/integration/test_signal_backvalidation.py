from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from core.config_models import SignalStrategyConfig
from data.asset_types import AssetClass
from data.models import OHLCVBar
from regime.regime_models import TrendRegime
from signals.signal_models import SignalDirection
from signals.strategies.mean_reversion import MeanReversionStrategy
from signals.strategies.momentum_breakout import MomentumBreakoutStrategy
from signals.strategies.trend_following import TrendFollowingStrategy
from tests.unit._signal_fixtures import make_regime


def _load_sample(path: Path, symbol: str, timeframe: str, broker: str = "mock") -> list[OHLCVBar]:
    frame = pl.read_parquet(path).sort("timestamp_open")
    rows = frame.to_dicts()
    out: list[OHLCVBar] = []
    for row in rows:
        out.append(
            OHLCVBar(
                symbol=symbol,
                broker=broker,
                timeframe=timeframe,
                timestamp_open=_to_dt(row["timestamp_open"]),
                timestamp_close=_to_dt(row["timestamp_close"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
                spread=float(row["spread"]) if row.get("spread") is not None else None,
                source="sample_data",
                asset_class=AssetClass.FOREX if "EURUSD" in symbol else AssetClass.CRYPTO,
            )
        )
    return out


def _to_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise TypeError(f"Unsupported datetime {value!r}")


def _generate_synthetic(
    *,
    total: int = 500,
    drift: float = 0.0002,
    noise: float = 0.0001,
) -> list[OHLCVBar]:
    bars: list[OHLCVBar] = []
    start = datetime.now(UTC) - timedelta(hours=total)
    price = 1.0
    for idx in range(total):
        variation = ((idx % 5) - 2) * noise
        open_price = price
        close = max(0.0001, open_price + drift + variation)
        high = max(open_price, close) + abs(variation)
        low = min(open_price, close) - abs(variation)
        ts_open = start + timedelta(hours=idx)
        bars.append(
            OHLCVBar(
                symbol="EURUSD",
                broker="mock",
                timeframe="H1",
                timestamp_open=ts_open,
                timestamp_close=ts_open + timedelta(hours=1),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
                source="synthetic",
                asset_class=AssetClass.FOREX,
            )
        )
        price = close
    return bars


async def _win_rate(strategy, bars: list[OHLCVBar], trend: TrendRegime) -> tuple[float, int]:
    wins = 0
    total = 0
    for idx in range(120, len(bars) - 1):
        subset = bars[: idx + 1]
        regime = make_regime(trend=trend)
        regime.metrics["adx"] = 30.0 if trend != TrendRegime.RANGING else 15.0
        signal = await strategy.generate(
            symbol=subset[-1].symbol,
            broker=subset[-1].broker,
            timeframe=subset[-1].timeframe,
            horizon="2h",
            bars=subset,
            regime=regime,
            timestamp=subset[-1].timestamp_close,
        )
        if signal is None or signal.direction not in {SignalDirection.BUY, SignalDirection.SELL}:
            continue
        total += 1
        future = bars[idx + 1].close
        current = bars[idx].close
        if signal.direction == SignalDirection.BUY and future > current:
            wins += 1
        if signal.direction == SignalDirection.SELL and future < current:
            wins += 1
    if total == 0:
        return 0.0, 0
    return wins / total, total


@pytest.mark.asyncio
async def test_relative_gate_eurusd_and_btc() -> None:
    eurusd = _load_sample(Path("tests/validation/sample_data/EURUSD_H1_2024.parquet"), "EURUSD", "H1")
    btc = _load_sample(Path("tests/validation/sample_data/BTCUSD_H1_2024.parquet"), "BTCUSD", "H1")

    trend = TrendFollowingStrategy(config=SignalStrategyConfig(strategy_id="trend_following"), run_id="run")
    momentum = MomentumBreakoutStrategy(
        config=SignalStrategyConfig(
            strategy_id="momentum_breakout",
            params={"lookback": 10, "volume_ratio_min": 0.9},
        ),
        run_id="run",
    )

    eur_rate, eur_trades = await _win_rate(trend, eurusd, TrendRegime.WEAK_UPTREND)
    btc_rate, btc_trades = await _win_rate(momentum, btc, TrendRegime.WEAK_UPTREND)

    baseline = 0.5
    delta = 0.03
    assert eur_trades >= 30
    assert btc_trades >= 30
    assert eur_rate >= baseline - 0.05
    assert btc_rate >= baseline - 0.05
    assert eur_rate >= (baseline - 0.05) + delta or btc_rate >= (baseline - 0.05) + delta


@pytest.mark.asyncio
async def test_trending_vs_ranging_relative_performance() -> None:
    trending_bars = _generate_synthetic(drift=0.0003, noise=0.00005)
    ranging_bars = _generate_synthetic(drift=0.0, noise=0.0002)

    trend = TrendFollowingStrategy(config=SignalStrategyConfig(strategy_id="trend_following"), run_id="run")
    mean = MeanReversionStrategy(config=SignalStrategyConfig(strategy_id="mean_reversion"), run_id="run")

    trend_win_trending, _ = await _win_rate(trend, trending_bars, TrendRegime.STRONG_UPTREND)
    mean_win_trending, _ = await _win_rate(mean, trending_bars, TrendRegime.STRONG_UPTREND)

    trend_win_ranging, _ = await _win_rate(trend, ranging_bars, TrendRegime.RANGING)
    mean_win_ranging, _ = await _win_rate(mean, ranging_bars, TrendRegime.RANGING)

    assert trend_win_trending >= mean_win_trending
    assert mean_win_ranging >= trend_win_ranging
