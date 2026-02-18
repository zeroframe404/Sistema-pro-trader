from __future__ import annotations

from data.asset_detector import AssetDetector
from data.asset_types import AssetClass, AssetMarket
from data.models import AssetInfo


class DummyConnector:
    broker = "mock"

    async def get_available_symbols(self) -> list[AssetInfo]:
        return [
            AssetInfo(
                symbol="EURUSD",
                broker="mock",
                name="EURUSD",
                asset_class=AssetClass.UNKNOWN,
                market=AssetMarket.UNKNOWN,
                currency="USD",
                contract_size=1,
                min_volume=0.01,
                max_volume=10,
                volume_step=0.01,
                pip_size=0.0001,
                digits=5,
                trading_hours={},
                available_timeframes=["M1"],
                supported_order_types=["MARKET"],
                extra={},
            )
        ]


def test_classify_symbol_covers_all_asset_types() -> None:
    detector = AssetDetector()
    cases = {
        "EURUSD": ("mt5", {}, AssetClass.FOREX),
        "EURUSD.CFD": ("mt5", {"type": "cfd"}, AssetClass.CFD),
        "AAPL": ("iol", {}, AssetClass.STOCK),
        "AL30": ("iol", {}, AssetClass.BOND),
        "LETE2026": ("iol", {}, AssetClass.TREASURY),
        "ONTEST": ("iol", {}, AssetClass.OBLIGATION),
        "GGAL-D": ("iol", {}, AssetClass.CEDEAR),
        "SPY": ("iol", {}, AssetClass.ETF),
        "XAUUSD": ("mt5", {}, AssetClass.COMMODITY),
        "SPX500": ("mt5", {}, AssetClass.INDEX),
        "BTCUSDT": ("ccxt", {}, AssetClass.CRYPTO),
        "ES1!": ("mt5", {"type": "future"}, AssetClass.FUTURES),
        "AAPL240119C150": ("iol", {}, AssetClass.OPTION),
        "EURUSD_OTC": ("iqoption", {"type": "binary"}, AssetClass.BINARY_OPTION),
        "PLAZO_FIJO": ("iol", {"type": "fixed"}, AssetClass.FIXED_TERM),
        "FCI_BALANCED": ("iol", {"type": "fund"}, AssetClass.MUTUAL_FUND),
        "CAUCION30": ("iol", {}, AssetClass.CAUTION),
        "LICITACION2026": ("iol", {}, AssetClass.AUCTION),
    }

    for symbol, (broker, metadata, expected) in cases.items():
        assert detector.classify_symbol(symbol, broker, metadata) == expected


async def test_detect_from_broker_classifies_assets() -> None:
    detector = AssetDetector()
    connector = DummyConnector()

    assets = await detector.detect_from_broker(connector)

    assert len(assets) == 1
    assert assets[0].asset_class == AssetClass.FOREX
