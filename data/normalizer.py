"""Broker payload normalization to internal data models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from data.asset_classifier import AssetClassifier
from data.asset_types import AssetClass
from data.models import OHLCVBar, Tick
from data.timezone_manager import TimezoneManager


class Normalizer:
    """Normalize raw broker payloads into internal models."""

    def __init__(self) -> None:
        self._tz_manager = TimezoneManager()
        self._classifier = AssetClassifier()

    def normalize_ohlcv_mt5(self, raw: dict[str, Any]) -> OHLCVBar:
        """Normalize MT5 rate payload to OHLCVBar."""

        symbol = self.normalize_symbol("mt5", str(raw.get("symbol", "UNKNOWN")))
        timeframe = self.normalize_timeframe("mt5", raw.get("timeframe", "M1"))
        open_dt = self._parse_timestamp(raw.get("time"), broker="mt5")
        close_dt = open_dt + timedelta(seconds=self._timeframe_seconds(timeframe))

        return OHLCVBar(
            symbol=symbol,
            broker="mt5",
            timeframe=timeframe,
            timestamp_open=open_dt,
            timestamp_close=close_dt,
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw.get("tick_volume", raw.get("real_volume", 0.0))),
            tick_count=int(raw.get("tick_volume", 0)) if raw.get("tick_volume") is not None else None,
            spread=float(raw.get("spread", 0.0)) if raw.get("spread") is not None else None,
            asset_class=self.detect_asset_class("mt5", symbol, raw),
            source="mt5",
        )

    def normalize_ohlcv_iqoption(self, raw: dict[str, Any]) -> OHLCVBar:
        """Normalize IQ Option candle payload."""

        symbol = self.normalize_symbol("iqoption", str(raw.get("symbol", "UNKNOWN")))
        timeframe = self.normalize_timeframe("iqoption", raw.get("timeframe", raw.get("size", 60)))
        open_dt = self._parse_timestamp(raw.get("from") or raw.get("open_time"), broker="iqoption")
        close_dt = self._parse_timestamp(raw.get("to") or raw.get("close_time"), broker="iqoption")

        return OHLCVBar(
            symbol=symbol,
            broker="iqoption",
            timeframe=timeframe,
            timestamp_open=open_dt,
            timestamp_close=close_dt,
            open=float(raw["open"]),
            high=float(raw["max"] if "max" in raw else raw["high"]),
            low=float(raw["min"] if "min" in raw else raw["low"]),
            close=float(raw["close"]),
            volume=float(raw.get("volume", 0.0)),
            tick_count=None,
            spread=None,
            asset_class=self.detect_asset_class("iqoption", symbol, raw),
            source="iqoption",
        )

    def normalize_ohlcv_iol(self, raw: dict[str, Any]) -> OHLCVBar:
        """Normalize IOL evolution payload."""

        symbol = self.normalize_symbol("iol", str(raw.get("symbol", raw.get("titulo", "UNKNOWN"))))
        timeframe = self.normalize_timeframe("iol", raw.get("timeframe", "D1"))
        open_dt = self._parse_timestamp(raw.get("fechaHora") or raw.get("fecha"), broker="iol")
        close_dt = open_dt + timedelta(seconds=self._timeframe_seconds(timeframe))

        return OHLCVBar(
            symbol=symbol,
            broker="iol",
            timeframe=timeframe,
            timestamp_open=open_dt,
            timestamp_close=close_dt,
            open=float(raw.get("apertura", raw.get("open", 0))),
            high=float(raw.get("maximo", raw.get("high", 0))),
            low=float(raw.get("minimo", raw.get("low", 0))),
            close=float(raw.get("ultimoPrecio", raw.get("close", 0))),
            volume=float(raw.get("volumenNominal", raw.get("volume", 0.0))),
            tick_count=None,
            spread=None,
            asset_class=self.detect_asset_class("iol", symbol, raw),
            source="iol",
        )

    def normalize_ohlcv_ccxt(self, raw: list[Any], *, symbol: str, broker: str = "ccxt") -> OHLCVBar:
        """Normalize CCXT OHLCV list payload."""

        timeframe = "M1"
        open_dt = self._parse_timestamp(raw[0], broker=broker)
        close_dt = open_dt + timedelta(seconds=self._timeframe_seconds(timeframe))
        normalized_symbol = self.normalize_symbol(broker, symbol)

        return OHLCVBar(
            symbol=normalized_symbol,
            broker=broker,
            timeframe=timeframe,
            timestamp_open=open_dt,
            timestamp_close=close_dt,
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=float(raw[5] if len(raw) > 5 else 0.0),
            tick_count=None,
            spread=None,
            asset_class=self.detect_asset_class(broker, normalized_symbol, {}),
            source=broker,
        )

    def normalize_tick_mt5(self, raw: dict[str, Any]) -> Tick:
        """Normalize MT5 tick payload."""

        symbol = self.normalize_symbol("mt5", str(raw.get("symbol", "UNKNOWN")))
        bid = float(raw["bid"])
        ask = float(raw["ask"])
        last_raw = raw.get("last")
        last_value = float(last_raw) if isinstance(last_raw, (int, float, str)) else (bid + ask) / 2

        return Tick(
            symbol=symbol,
            broker="mt5",
            timestamp=self._parse_timestamp(raw.get("time_msc", raw.get("time")), broker="mt5"),
            bid=bid,
            ask=ask,
            last=last_value,
            volume=float(raw.get("volume", 0.0)) if raw.get("volume") is not None else None,
            spread=ask - bid,
            asset_class=self.detect_asset_class("mt5", symbol, raw),
            source="mt5",
        )

    def normalize_tick_iqoption(self, raw: dict[str, Any]) -> Tick:
        """Normalize IQ Option tick payload."""

        symbol = self.normalize_symbol("iqoption", str(raw.get("active", raw.get("symbol", "UNKNOWN"))))
        bid = float(raw.get("bid", raw.get("price", 0)))
        ask = float(raw.get("ask", raw.get("price", 0)))

        return Tick(
            symbol=symbol,
            broker="iqoption",
            timestamp=self._parse_timestamp(raw.get("timestamp") or raw.get("time"), broker="iqoption"),
            bid=bid,
            ask=ask,
            last=float(raw.get("price", (bid + ask) / 2)),
            volume=float(raw.get("volume", 0.0)) if raw.get("volume") is not None else None,
            spread=ask - bid,
            asset_class=self.detect_asset_class("iqoption", symbol, raw),
            source="iqoption",
        )

    def normalize_tick_ccxt(self, raw: dict[str, Any], *, broker: str = "ccxt") -> Tick:
        """Normalize CCXT trade/ticker payload."""

        symbol = self.normalize_symbol(broker, str(raw.get("symbol", "UNKNOWN")))
        bid = float(raw.get("bid", raw.get("last", 0.0)))
        ask = float(raw.get("ask", raw.get("last", bid)))

        return Tick(
            symbol=symbol,
            broker=broker,
            timestamp=self._parse_timestamp(raw.get("timestamp") or raw.get("datetime"), broker=broker),
            bid=bid,
            ask=ask,
            last=float(raw.get("last", (bid + ask) / 2)),
            volume=float(raw.get("baseVolume", raw.get("amount", 0.0))) if raw.get("baseVolume") is not None or raw.get("amount") is not None else None,
            spread=ask - bid,
            asset_class=self.detect_asset_class(broker, symbol, raw),
            source=broker,
        )

    def normalize_timeframe(self, broker: str, raw_tf: str | int) -> str:
        """Map broker timeframe format to internal canonical format."""

        broker_name = broker.lower()
        value = str(raw_tf).upper()

        mt5_map = {
            "TIMEFRAME_M1": "M1",
            "TIMEFRAME_M5": "M5",
            "TIMEFRAME_M15": "M15",
            "TIMEFRAME_M30": "M30",
            "TIMEFRAME_H1": "H1",
            "TIMEFRAME_H4": "H4",
            "TIMEFRAME_D1": "D1",
            "TIMEFRAME_W1": "W1",
            "TIMEFRAME_MN1": "MN1",
        }
        iq_map = {"60": "M1", "300": "M5", "900": "M15", "1800": "M30", "3600": "H1", "86400": "D1"}
        ccxt_map = {"1M": "M1", "5M": "M5", "15M": "M15", "30M": "M30", "1H": "H1", "4H": "H4", "1D": "D1", "1W": "W1", "1MO": "MN1"}
        iol_map = {"MINUTO": "M1", "DIARIO": "D1", "SEMANAL": "W1", "MENSUAL": "MN1"}

        if broker_name == "mt5":
            return mt5_map.get(value, value)
        if broker_name == "iqoption":
            return iq_map.get(value, value if value.startswith(("M", "H", "D", "W")) else "M1")
        if broker_name in {"ccxt", "binance", "bybit", "okx", "kraken"}:
            return ccxt_map.get(value, value)
        if broker_name == "iol":
            return iol_map.get(value, value)

        return value

    def normalize_symbol(self, broker: str, raw_symbol: str) -> str:
        """Map broker symbol to internal symbol format."""

        symbol = raw_symbol.strip().upper()
        broker_name = broker.lower()

        if broker_name in {"ccxt", "binance", "bybit", "okx", "kraken"}:
            symbol = symbol.replace("/", "")

        if broker_name == "iqoption":
            symbol = symbol.replace("-", "_")

        return symbol

    def detect_asset_class(self, broker: str, symbol: str, metadata: dict[str, Any]) -> AssetClass:
        """Detect asset class for normalized symbol and metadata."""

        return self._classifier.classify_symbol(symbol=symbol, broker=broker, metadata=metadata)

    def _parse_timestamp(self, value: Any, *, broker: str) -> datetime:
        if isinstance(value, datetime):
            return value.astimezone(UTC) if value.tzinfo is not None else self._tz_manager.to_utc(value, broker)

        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC) if parsed.tzinfo is not None else self._tz_manager.to_utc(parsed, broker)

        if isinstance(value, (int, float)):
            if value > 10_000_000_000:
                return datetime.fromtimestamp(value / 1000, tz=UTC)
            return datetime.fromtimestamp(value, tz=UTC)

        return datetime.now(UTC)

    @staticmethod
    def _timeframe_seconds(timeframe: str) -> int:
        mapping = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "M30": 1800,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
            "W1": 604800,
            "MN1": 2592000,
        }
        return mapping.get(timeframe.upper(), 60)
