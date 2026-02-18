from __future__ import annotations

from data.asset_types import AssetClass
from data.normalizer import Normalizer


def test_normalize_mt5_bar() -> None:
    normalizer = Normalizer()
    raw = {
        "symbol": "EURUSD",
        "timeframe": "TIMEFRAME_M1",
        "time": 1_704_067_200,
        "open": 1.1,
        "high": 1.2,
        "low": 1.0,
        "close": 1.15,
        "tick_volume": 120,
        "spread": 0.0001,
    }

    bar = normalizer.normalize_ohlcv_mt5(raw)

    assert bar.symbol == "EURUSD"
    assert bar.timeframe == "M1"
    assert bar.volume == 120


def test_normalize_ccxt_bar() -> None:
    normalizer = Normalizer()
    raw = [1_704_067_200_000, 10.0, 12.0, 9.0, 11.0, 100.0]

    bar = normalizer.normalize_ohlcv_ccxt(raw, symbol="BTC/USDT", broker="ccxt")

    assert bar.symbol == "BTCUSDT"
    assert bar.open == 10.0
    assert bar.close == 11.0


def test_normalize_timeframe_mappings() -> None:
    normalizer = Normalizer()

    assert normalizer.normalize_timeframe("mt5", "TIMEFRAME_M1") == "M1"
    assert normalizer.normalize_timeframe("iqoption", 60) == "M1"
    assert normalizer.normalize_timeframe("ccxt", "1m") == "M1"
    assert normalizer.normalize_timeframe("iol", "minuto") == "M1"


def test_normalize_symbol() -> None:
    normalizer = Normalizer()

    assert normalizer.normalize_symbol("mt5", "EURUSD") == "EURUSD"
    assert normalizer.normalize_symbol("ccxt", "BTC/USDT") == "BTCUSDT"
    assert normalizer.normalize_symbol("iqoption", "EURUSD-OTC") == "EURUSD_OTC"


def test_detect_asset_class_examples() -> None:
    normalizer = Normalizer()

    assert normalizer.detect_asset_class("mt5", "EURUSD", {}) == AssetClass.FOREX
    assert normalizer.detect_asset_class("ccxt", "BTCUSDT", {}) == AssetClass.CRYPTO
    assert normalizer.detect_asset_class("iol", "GGAL-D", {}) == AssetClass.CEDEAR
