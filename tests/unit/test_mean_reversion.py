from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.config_models import SignalStrategyConfig
from data.asset_types import AssetClass
from data.models import OHLCVBar
from regime.regime_models import TrendRegime
from signals.signal_models import SignalDirection
from signals.strategies.mean_reversion import MeanReversionStrategy
from tests.unit._signal_fixtures import make_regime


def _bars_from_closes(closes: list[float]) -> list[OHLCVBar]:
    start = datetime.now(UTC) - timedelta(hours=len(closes))
    bars: list[OHLCVBar] = []
    for idx, close in enumerate(closes):
        open_price = closes[idx - 1] if idx > 0 else close
        high = max(open_price, close) + 0.001
        low = min(open_price, close) - 0.001
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
                source="test",
                asset_class=AssetClass.FOREX,
            )
        )
    return bars


@pytest.mark.asyncio
async def test_oversold_setup_returns_buy() -> None:
    config = SignalStrategyConfig(strategy_id="mean_reversion", params={"rsi_low": 30, "rsi_high": 70})
    strategy = MeanReversionStrategy(config=config, run_id="run")
    closes = [1.2 - (i * 0.001) for i in range(40)]
    regime = make_regime(trend=TrendRegime.RANGING)
    signal = await strategy.generate(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        horizon="2h",
        bars=_bars_from_closes(closes),
        regime=regime,
        timestamp=datetime.now(UTC),
    )
    assert signal is not None
    assert signal.direction == SignalDirection.BUY


@pytest.mark.asyncio
async def test_overbought_setup_returns_sell() -> None:
    config = SignalStrategyConfig(strategy_id="mean_reversion", params={"rsi_low": 30, "rsi_high": 70})
    strategy = MeanReversionStrategy(config=config, run_id="run")
    closes = [1.0 + (i * 0.001) for i in range(40)]
    regime = make_regime(trend=TrendRegime.RANGING)
    signal = await strategy.generate(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        horizon="2h",
        bars=_bars_from_closes(closes),
        regime=regime,
        timestamp=datetime.now(UTC),
    )
    assert signal is not None
    assert signal.direction == SignalDirection.SELL


@pytest.mark.asyncio
async def test_flat_conditions_return_wait() -> None:
    config = SignalStrategyConfig(strategy_id="mean_reversion")
    strategy = MeanReversionStrategy(config=config, run_id="run")
    closes = [1.1 + ((-1) ** i) * 0.0001 for i in range(40)]
    regime = make_regime(trend=TrendRegime.RANGING)
    signal = await strategy.generate(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        horizon="2h",
        bars=_bars_from_closes(closes),
        regime=regime,
        timestamp=datetime.now(UTC),
    )
    assert signal is not None
    assert signal.direction == SignalDirection.WAIT


@pytest.mark.asyncio
async def test_strong_trend_reduces_confidence() -> None:
    config = SignalStrategyConfig(strategy_id="mean_reversion", params={"rsi_low": 30, "rsi_high": 70})
    strategy = MeanReversionStrategy(config=config, run_id="run")
    closes = [1.2 - (i * 0.001) for i in range(40)]
    ranging = make_regime(trend=TrendRegime.RANGING)
    trending = make_regime(trend=TrendRegime.STRONG_UPTREND)
    signal_ranging = await strategy.generate(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        horizon="2h",
        bars=_bars_from_closes(closes),
        regime=ranging,
        timestamp=datetime.now(UTC),
    )
    signal_trending = await strategy.generate(
        symbol="EURUSD",
        broker="mock",
        timeframe="H1",
        horizon="2h",
        bars=_bars_from_closes(closes),
        regime=trending,
        timestamp=datetime.now(UTC),
    )
    assert signal_ranging is not None
    assert signal_trending is not None
    assert signal_trending.confidence < signal_ranging.confidence
