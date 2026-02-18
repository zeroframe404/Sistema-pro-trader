from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from data.asset_types import AssetClass, AssetMarket
from data.models import AssetInfo, DataQualityReport, Tick
from storage.sqlite_store import SQLiteStore


@pytest.mark.asyncio
async def test_save_and_get_asset_info(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "store.db")
    await store.initialize()

    asset = AssetInfo(
        symbol="AAPL",
        broker="iol",
        name="Apple",
        asset_class=AssetClass.STOCK,
        market=AssetMarket.NASDAQ,
        currency="USD",
        contract_size=1,
        min_volume=1,
        max_volume=100,
        volume_step=1,
        pip_size=0.01,
        digits=2,
        trading_hours={},
        available_timeframes=["D1"],
        supported_order_types=["MARKET"],
        extra={},
    )

    await store.save_asset_info(asset)
    loaded = await store.get_asset_info("AAPL", "iol")

    assert loaded == asset


@pytest.mark.asyncio
async def test_list_assets_filtered_by_class(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "store.db")
    await store.initialize()

    stock = AssetInfo(
        symbol="AAPL",
        broker="iol",
        name="Apple",
        asset_class=AssetClass.STOCK,
        market=AssetMarket.NASDAQ,
        currency="USD",
        contract_size=1,
        min_volume=1,
        max_volume=100,
        volume_step=1,
        pip_size=0.01,
        digits=2,
        trading_hours={},
        available_timeframes=["D1"],
        supported_order_types=["MARKET"],
        extra={},
    )
    crypto = stock.model_copy(update={"symbol": "BTCUSDT", "asset_class": AssetClass.CRYPTO, "broker": "ccxt"})

    await store.save_asset_info(stock)
    await store.save_asset_info(crypto)

    stocks = await store.list_assets(asset_class=AssetClass.STOCK)

    assert len(stocks) == 1
    assert stocks[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_save_and_get_quality_report(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "store.db")
    await store.initialize()

    report = DataQualityReport(
        symbol="EURUSD",
        broker="mock",
        timeframe="M1",
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 2, tzinfo=UTC),
        total_bars=100,
        missing_bars=1,
        duplicate_bars=0,
        corrupt_bars=0,
        outlier_bars=0,
        timezone_issues=0,
        gap_details=[],
        quality_score=0.99,
        is_usable=True,
    )

    await store.save_quality_report(report)
    loaded = await store.get_latest_quality_report("EURUSD", "mock", "M1")

    assert loaded is not None
    assert loaded.quality_score == report.quality_score


@pytest.mark.asyncio
async def test_update_and_get_last_price(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "store.db")
    await store.initialize()

    tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=datetime.now(UTC),
        bid=1.1,
        ask=1.2,
        last=1.15,
        volume=1,
        spread=0.1,
        asset_class=AssetClass.FOREX,
        source="mock",
    )

    await store.update_last_price(tick)
    loaded = await store.get_last_price("EURUSD", "mock")

    assert loaded is not None
    assert loaded.symbol == "EURUSD"
