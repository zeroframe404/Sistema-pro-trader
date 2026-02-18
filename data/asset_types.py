"""Asset and market type enumerations."""

from __future__ import annotations

from enum import StrEnum


class AssetClass(StrEnum):
    """Supported asset classes."""

    FOREX = "forex"
    CFD = "cfd"
    STOCK = "stock"
    BOND = "bond"
    TREASURY = "treasury"
    OBLIGATION = "obligation"
    CEDEAR = "cedear"
    ETF = "etf"
    COMMODITY = "commodity"
    INDEX = "index"
    CRYPTO = "crypto"
    FUTURES = "futures"
    OPTION = "option"
    BINARY_OPTION = "binary_option"
    FIXED_TERM = "fixed_term"
    MUTUAL_FUND = "mutual_fund"
    CAUTION = "caution"
    AUCTION = "auction"
    UNKNOWN = "unknown"


class AssetMarket(StrEnum):
    """Markets/exchanges where an asset is traded."""

    BYMA = "byma"
    NYSE = "nyse"
    NASDAQ = "nasdaq"
    CME = "cme"
    FOREX_OTC = "forex_otc"
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_FUTURES = "crypto_futures"
    BINANCE = "binance"
    OTC_BINARY = "otc_binary"
    UNKNOWN = "unknown"


class TradingHorizon(StrEnum):
    """Trading horizon labels."""

    SCALP = "scalp"
    INTRADAY = "intraday"
    SWING = "swing"
    POSITION = "position"
    INVESTMENT = "investment"
