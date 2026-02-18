from __future__ import annotations

import pytest

from data.asset_types import AssetClass
from data.models import Tick
from regime.market_conditions import MarketConditionsChecker
from tests.unit._indicator_fixtures import make_bars


@pytest.mark.asyncio
async def test_spread_spike_reason() -> None:
    bars = make_bars([1.0 + i * 0.001 for i in range(120)])
    checker = MarketConditionsChecker(spread_spike_multiplier=3.0)
    tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=bars[-1].timestamp_close,
        bid=1.0,
        ask=1.02,
        last=1.01,
        volume=100,
        spread=0.02,
        asset_class=AssetClass.FOREX,
        source="test",
    )

    reasons = await checker.check("EURUSD", "mock", AssetClass.FOREX, tick, bars)
    assert "spread_spike" in reasons


@pytest.mark.asyncio
async def test_low_volume_reason() -> None:
    bars = make_bars([1.0 + i * 0.001 for i in range(120)])
    for bar in bars[:-1]:
        bar.volume = 1000
    bars[-1].volume = 1

    checker = MarketConditionsChecker()
    tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=bars[-1].timestamp_close,
        bid=1.0,
        ask=1.0001,
        last=1.00005,
        volume=1,
        spread=0.0001,
        asset_class=AssetClass.FOREX,
        source="test",
    )

    reasons = await checker.check("EURUSD", "mock", AssetClass.FOREX, tick, bars)
    assert "low_volume" in reasons


@pytest.mark.asyncio
async def test_crypto_never_bad_session() -> None:
    bars = make_bars([1.0 + i * 0.001 for i in range(120)], symbol="BTCUSD")
    checker = MarketConditionsChecker()
    tick = Tick(
        symbol="BTCUSD",
        broker="mock",
        timestamp=bars[-1].timestamp_close,
        bid=30000,
        ask=30000.5,
        last=30000.2,
        volume=100,
        spread=0.5,
        asset_class=AssetClass.CRYPTO,
        source="test",
    )

    reasons = await checker.check("BTCUSD", "mock", AssetClass.CRYPTO, tick, bars)
    assert "bad_session" not in reasons


@pytest.mark.asyncio
async def test_price_freeze_reason() -> None:
    bars = make_bars([1.0] * 120)
    checker = MarketConditionsChecker()
    tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=bars[-1].timestamp_close,
        bid=1.0,
        ask=1.0001,
        last=1.0,
        volume=100,
        spread=0.0001,
        asset_class=AssetClass.FOREX,
        source="test",
    )

    reasons = await checker.check("EURUSD", "mock", AssetClass.FOREX, tick, bars)
    assert "price_freeze" in reasons
