"""Symbol classification heuristics."""

from __future__ import annotations

import re
from typing import Any

from data.asset_types import AssetClass

FOREX_PAIR_RE = re.compile(r"^[A-Z]{6}(?:_OTC)?$")
OPTION_RE = re.compile(r"^[A-Z]{1,6}\d{6,8}[CP]\d+$")

KNOWN_ETFS = {"SPY", "QQQ", "DIA", "IWM", "EEM", "GLD", "XLF"}
KNOWN_INDEXES = {"SPX", "SPX500", "US30", "DJI", "NDX", "MERVAL", "IBEX"}
KNOWN_COMMODITIES = {"XAUUSD", "XAGUSD", "CL", "BRENT", "NG"}
KNOWN_FUTURES_PREFIX = ("ES", "NQ", "YM", "ZN", "ZC", "GC", "SI")
KNOWN_BONDS_PREFIX = ("AL", "GD", "BON", "TBOND", "BOND")
KNOWN_TREASURY_PREFIX = ("LETE", "LECAP", "TBILL", "UST")


class AssetClassifier:
    """Classify symbols into normalized asset classes."""

    def classify_symbol(self, symbol: str, broker: str, metadata: dict[str, Any] | None = None) -> AssetClass:
        """Return the best-effort asset class for a symbol."""

        metadata = metadata or {}
        normalized = symbol.upper().replace("/", "").strip()
        market_hint = str(metadata.get("market", "")).lower()
        type_hint = str(metadata.get("type", metadata.get("asset_type", ""))).lower()

        if "binary" in type_hint or "otc_binary" in market_hint:
            return AssetClass.BINARY_OPTION

        if "caucion" in normalized.lower() or "caution" in type_hint:
            return AssetClass.CAUTION

        if "licit" in normalized.lower() or "auction" in type_hint:
            return AssetClass.AUCTION

        if "fci" in normalized.lower() or "mutual" in type_hint or "fund" in type_hint:
            return AssetClass.MUTUAL_FUND

        if "plazo" in normalized.lower() or "fixed" in type_hint:
            return AssetClass.FIXED_TERM

        if "obligation" in type_hint or normalized.startswith("ON"):
            return AssetClass.OBLIGATION

        if "cedear" in type_hint or normalized.endswith("-D"):
            return AssetClass.CEDEAR

        if "treasury" in type_hint or normalized.startswith(KNOWN_TREASURY_PREFIX):
            return AssetClass.TREASURY

        if "bond" in type_hint or normalized.startswith(KNOWN_BONDS_PREFIX):
            return AssetClass.BOND

        if normalized in KNOWN_ETFS or "etf" in type_hint:
            return AssetClass.ETF

        if normalized in KNOWN_INDEXES or "index" in type_hint:
            return AssetClass.INDEX

        if normalized in KNOWN_COMMODITIES or "commodity" in type_hint:
            return AssetClass.COMMODITY

        if normalized.endswith("1!") or normalized.startswith(KNOWN_FUTURES_PREFIX):
            if "future" in type_hint or normalized.endswith("1!"):
                return AssetClass.FUTURES

        if OPTION_RE.match(normalized) or "option" in type_hint:
            return AssetClass.OPTION

        if (
            "crypto" in type_hint
            or normalized.endswith("USDT")
            or normalized.endswith("BTC")
            or normalized.endswith("ETH")
            or broker.lower() in {"ccxt", "binance", "bybit", "okx", "kraken"}
        ):
            return AssetClass.CRYPTO

        if FOREX_PAIR_RE.match(normalized):
            return AssetClass.FOREX

        if broker.lower() in {"mt5", "fxpro"} and "cfd" in type_hint:
            return AssetClass.CFD

        if normalized.isalpha() and 1 <= len(normalized) <= 6:
            return AssetClass.STOCK

        return AssetClass.UNKNOWN


def classify_symbol(symbol: str, broker: str, metadata: dict[str, Any] | None = None) -> AssetClass:
    """Convenience wrapper for symbol classification."""

    return AssetClassifier().classify_symbol(symbol=symbol, broker=broker, metadata=metadata)
