from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.config_models import SignalStrategyConfig
from data.asset_types import AssetClass
from data.models import OHLCVBar
from regime.regime_models import TrendRegime
from signals.signal_models import SignalDirection
from signals.strategies.trend_following import TrendFollowingStrategy
from tests.unit._signal_fixtures import make_regime


def _bars_from_closes(closes: list[float]) -> list[OHLCVBar]:
    start = datetime.now(UTC) - timedelta(hours=len(closes))
    bars: list[OHLCVBar] = []
    for idx, close in enumerate(closes):
        open_price = closes[idx - 1] if idx > 0 else close
        high = max(open_price, close) + 0.0005
        low = min(open_price, close) - 0.0005
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
async def test_bullish_structure_generates_buy() -> None:
    config = SignalStrategyConfig(strategy_id="trend_following", params={"adx_min": 20})
    strategy = TrendFollowingStrategy(config=config, run_id="run")
    closes = [1.0 + i * 0.001 for i in range(260)]
    regime = make_regime(trend=TrendRegime.STRONG_UPTREND)
    regime.metrics["adx"] = 30.0
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
async def test_bearish_structure_generates_sell() -> None:
    config = SignalStrategyConfig(strategy_id="trend_following", params={"adx_min": 20})
    strategy = TrendFollowingStrategy(config=config, run_id="run")
    closes = [2.0 - i * 0.001 for i in range(260)]
    regime = make_regime(trend=TrendRegime.STRONG_DOWNTREND)
    regime.metrics["adx"] = 30.0
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
async def test_low_adx_returns_wait() -> None:
    config = SignalStrategyConfig(strategy_id="trend_following", params={"adx_min": 20})
    strategy = TrendFollowingStrategy(config=config, run_id="run")
    closes = [1.0 + i * 0.001 for i in range(260)]
    regime = make_regime(trend=TrendRegime.RANGING)
    regime.metrics["adx"] = 15.0
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
async def test_overbought_rsi_reduces_buy_confidence() -> None:
    config = SignalStrategyConfig(strategy_id="trend_following", params={"adx_min": 20, "overbought_rsi": 70})
    strategy = TrendFollowingStrategy(config=config, run_id="run")
    closes = [1.0 + i * 0.002 for i in range(260)]
    regime = make_regime(trend=TrendRegime.STRONG_UPTREND)
    regime.metrics["adx"] = 30.0
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
    assert signal.confidence < 0.8


@pytest.mark.asyncio
async def test_reasons_include_ema_cross_bullish() -> None:
    config = SignalStrategyConfig(strategy_id="trend_following", params={"adx_min": 20})
    strategy = TrendFollowingStrategy(config=config, run_id="run")
    closes = [1.0 + i * 0.001 for i in range(260)]
    regime = make_regime(trend=TrendRegime.STRONG_UPTREND)
    regime.metrics["adx"] = 30.0
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
    assert any(reason.factor == "EMA_cross" and reason.direction == "bullish" for reason in signal.reasons)
