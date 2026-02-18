from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from data.asset_types import AssetClass, AssetMarket
from data.models import AssetInfo, OHLCVBar, Tick


def _valid_bar_kwargs() -> dict:
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return {
        "symbol": "EURUSD",
        "broker": "mock",
        "timeframe": "M1",
        "timestamp_open": start,
        "timestamp_close": start + timedelta(minutes=1),
        "open": 1.1,
        "high": 1.2,
        "low": 1.0,
        "close": 1.15,
        "volume": 100,
        "asset_class": AssetClass.FOREX,
        "source": "mock",
    }


def test_ohlcv_fails_when_high_less_than_low() -> None:
    kwargs = _valid_bar_kwargs()
    kwargs["high"] = 0.9
    with pytest.raises(ValidationError):
        OHLCVBar(**kwargs)


def test_ohlcv_fails_when_open_non_positive() -> None:
    kwargs = _valid_bar_kwargs()
    kwargs["open"] = 0.0
    with pytest.raises(ValidationError):
        OHLCVBar(**kwargs)


def test_ohlcv_fails_when_close_time_not_after_open() -> None:
    kwargs = _valid_bar_kwargs()
    kwargs["timestamp_close"] = kwargs["timestamp_open"]
    with pytest.raises(ValidationError):
        OHLCVBar(**kwargs)


def test_tick_fails_when_bid_greater_than_ask() -> None:
    with pytest.raises(ValidationError):
        Tick(
            symbol="EURUSD",
            broker="mock",
            timestamp=datetime.now(UTC),
            bid=1.2,
            ask=1.1,
            last=1.15,
            volume=1,
            spread=0.1,
            asset_class=AssetClass.FOREX,
            source="mock",
        )


def test_asset_info_json_roundtrip() -> None:
    asset = AssetInfo(
        symbol="AAPL",
        broker="iol",
        name="Apple",
        asset_class=AssetClass.STOCK,
        market=AssetMarket.NASDAQ,
        currency="USD",
        base_currency=None,
        quote_currency=None,
        contract_size=1,
        min_volume=1,
        max_volume=1000,
        volume_step=1,
        pip_size=0.01,
        digits=2,
        trading_hours={"monday": ["09:30-16:00"]},
        available_timeframes=["D1"],
        supported_order_types=["MARKET"],
        extra={"sector": "tech"},
    )

    payload = asset.model_dump_json()
    restored = AssetInfo.model_validate_json(payload)

    assert restored == asset
