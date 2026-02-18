"""Central indicator orchestration engine."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any, cast

from core.events import BarCloseEvent
from data.asset_types import AssetClass
from data.models import OHLCVBar
from data.resampler import Resampler
from indicators.base_indicator import BaseIndicator
from indicators.indicator_backend import IndicatorBackend
from indicators.indicator_result import IndicatorSeries, IndicatorValue
from indicators.momentum.cci import CCI
from indicators.momentum.macd import MACD
from indicators.momentum.mfi import MFI
from indicators.momentum.rsi import RSI
from indicators.momentum.stochastic import Stochastic, StochRSI
from indicators.momentum.williams_r import WilliamsR
from indicators.patterns.candlestick_patterns import CandlestickPatterns
from indicators.patterns.support_resistance import SupportResistance
from indicators.trend.adx import ADX
from indicators.trend.ichimoku import Ichimoku
from indicators.trend.moving_averages import DEMA, EMA, HMA, SMA, TEMA, WMA
from indicators.trend.parabolic_sar import ParabolicSAR
from indicators.trend.supertrend import SuperTrend
from indicators.volatility.atr import ATR
from indicators.volatility.bollinger_bands import BollingerBands
from indicators.volatility.keltner_channel import KeltnerChannel
from indicators.volatility.vix_proxy import VIXProxy
from indicators.volume.cmf import CMF
from indicators.volume.obv import OBV
from indicators.volume.volume_profile import VolumeProfile
from indicators.volume.vwap import VWAP
from storage.data_repository import DataRepository


@dataclass(slots=True)
class _CacheEntry:
    created_at: float
    result: IndicatorSeries


class IndicatorEngine:
    """Compute and cache indicator values for bar series."""

    def __init__(
        self,
        *,
        data_repository: DataRepository | None = None,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = 60,
        max_lookback_bars: int = 1000,
        backend_preference: str = "auto",
    ) -> None:
        self._data_repository = data_repository
        self._cache_enabled = cache_enabled
        self._cache_ttl_seconds = cache_ttl_seconds
        self._max_lookback_bars = max_lookback_bars
        self._backend = IndicatorBackend(preference=backend_preference)
        self._resampler = Resampler()
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

        self._indicator_types: dict[str, type[BaseIndicator]] = {
            "SMA": SMA,
            "EMA": EMA,
            "WMA": WMA,
            "DEMA": DEMA,
            "TEMA": TEMA,
            "HMA": HMA,
            "ADX": ADX,
            "SUPERTREND": SuperTrend,
            "ICHIMOKU": Ichimoku,
            "PARABOLICSAR": ParabolicSAR,
            "RSI": RSI,
            "MACD": MACD,
            "STOCHASTIC": Stochastic,
            "STOCHRSI": StochRSI,
            "CCI": CCI,
            "MFI": MFI,
            "WILLIAMSR": WilliamsR,
            "ATR": ATR,
            "BOLLINGERBANDS": BollingerBands,
            "KELTNERCHANNEL": KeltnerChannel,
            "VIXPROXY": VIXProxy,
            "OBV": OBV,
            "VWAP": VWAP,
            "VOLUMEPROFILE": VolumeProfile,
            "CMF": CMF,
            "CANDLESTICKPATTERNS": CandlestickPatterns,
            "SUPPORTRESISTANCE": SupportResistance,
        }

        self._dependencies: dict[str, list[str]] = {
            "SUPERTREND": ["ATR"],
            "KELTNERCHANNEL": ["ATR", "EMA"],
        }

    def register_indicator(self, indicator_id: str, indicator_cls: type[BaseIndicator]) -> None:
        """Register custom indicator implementation."""

        self._indicator_types[indicator_id.upper()] = indicator_cls

    async def compute(
        self,
        indicator_id: str,
        bars: list[OHLCVBar],
        **params: object,
    ) -> IndicatorSeries:
        """Compute one indicator with optional cache reuse."""

        normalized_id = self._normalize_id(indicator_id)
        cache_key = self._build_cache_key(normalized_id, bars, params)

        if self._cache_enabled:
            cached = self._cache.get(cache_key)
            if cached is not None and (time.time() - cached.created_at) <= self._cache_ttl_seconds:
                return cached.result

        indicator = self._make_indicator(normalized_id)
        result = indicator.compute(bars, **params)

        if self._cache_enabled:
            self._cache[cache_key] = _CacheEntry(created_at=time.time(), result=result)

        return result

    async def compute_batch(
        self,
        indicators: list[dict[str, object]],
        bars: list[OHLCVBar],
    ) -> dict[str, IndicatorSeries]:
        """Compute a batch of indicators with dependency ordering."""

        normalized_specs = [spec for spec in (self._normalize_spec(item) for item in indicators) if spec is not None]
        if not normalized_specs:
            return {}

        requested_ids = [str(spec["id"]) for spec in normalized_specs]
        ordered_ids = self.get_dependency_order(requested_ids)

        # Add synthetic dependency specs if needed.
        by_id: dict[str, list[dict[str, object]]] = {}
        for spec in normalized_specs:
            by_id.setdefault(str(spec["id"]), []).append(spec)
        for dep_id in ordered_ids:
            by_id.setdefault(dep_id, [{"id": dep_id, "params": {}, "requested": False}])

        results: dict[str, IndicatorSeries] = {}
        async with self._lock:
            for dep_id in ordered_ids:
                for spec in by_id.get(dep_id, []):
                    raw_params = spec.get("params", {})
                    indicator_params = (
                        {str(key): value for key, value in raw_params.items()}
                        if isinstance(raw_params, dict)
                        else {}
                    )
                    series = await self.compute(dep_id, bars, **indicator_params)
                    if bool(spec.get("requested", True)):
                        result_key = self._spec_key(spec)
                        results[result_key] = series

        return results

    async def compute_for_bar(
        self,
        bar: BarCloseEvent,
        indicators: list[dict[str, object]],
        lookback_bars: int = 500,
    ) -> dict[str, IndicatorValue]:
        """Compute latest indicator values for a just-closed bar."""

        if self._data_repository is None:
            raise RuntimeError("IndicatorEngine requires data_repository for compute_for_bar")

        tf_seconds = self._resampler.get_timeframe_seconds(bar.timeframe)
        lookback = max(10, min(lookback_bars, self._max_lookback_bars))
        start = bar.timestamp_open.astimezone(UTC) - timedelta(seconds=(tf_seconds * lookback))
        end = bar.timestamp_close.astimezone(UTC)

        bars = await self._data_repository.get_ohlcv(
            symbol=bar.symbol,
            broker=bar.broker,
            timeframe=bar.timeframe,
            start=start,
            end=end,
            auto_fetch=True,
        )

        if not bars or bars[-1].timestamp_close != bar.timestamp_close:
            bars.append(
                OHLCVBar(
                    symbol=bar.symbol,
                    broker=bar.broker,
                    timeframe=bar.timeframe,
                    timestamp_open=bar.timestamp_open,
                    timestamp_close=bar.timestamp_close,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    source="event_bus",
                    asset_class=bars[-1].asset_class if bars else AssetClass.UNKNOWN,
                )
            )

        batch = await self.compute_batch(indicators, bars)
        output: dict[str, IndicatorValue] = {}
        for key, series in batch.items():
            if series.values:
                output[key] = series.values[-1]
        return output

    def get_dependency_order(self, indicators: list[str]) -> list[str]:
        """Return dependency-resolved order for requested indicators."""

        requested = [self._normalize_id(item) for item in indicators]
        resolved: list[str] = []
        visiting: set[str] = set()

        def visit(node: str) -> None:
            if node in resolved:
                return
            if node in visiting:
                return
            visiting.add(node)
            for dep in self._dependencies.get(node, []):
                visit(dep)
            visiting.remove(node)
            resolved.append(node)

        for indicator in requested:
            visit(indicator)

        return resolved

    def invalidate_cache(self, symbol: str, timeframe: str) -> None:
        """Clear cached results for one symbol/timeframe."""

        needle = f"{symbol}|{timeframe}|"
        keys = [key for key in self._cache if needle in key]
        for key in keys:
            self._cache.pop(key, None)

    def _make_indicator(self, indicator_id: str) -> BaseIndicator:
        cls = self._indicator_types.get(indicator_id)
        if cls is None:
            raise KeyError(f"Unsupported indicator: {indicator_id}")
        ctor = cast(Any, cls)
        return cast(BaseIndicator, ctor(backend=self._backend))

    @staticmethod
    def _normalize_id(indicator_id: str) -> str:
        return indicator_id.replace(" ", "").replace("_", "").upper()

    def _normalize_spec(self, spec: dict[str, object] | None) -> dict[str, object] | None:
        if spec is None:
            return None
        indicator_id = spec.get("id")
        if not isinstance(indicator_id, str):
            return None

        enabled = spec.get("enabled", True)
        if isinstance(enabled, bool) and not enabled:
            return None

        params = spec.get("params")
        if isinstance(params, dict):
            normalized_params = {str(key): value for key, value in params.items()}
        else:
            normalized_params = {}

        out: dict[str, object] = {
            "id": self._normalize_id(indicator_id),
            "params": normalized_params,
            "requested": True,
        }
        if "key" in spec and isinstance(spec["key"], str):
            out["key"] = spec["key"]
        return out

    def _build_cache_key(
        self,
        normalized_id: str,
        bars: list[OHLCVBar],
        params: dict[str, object],
    ) -> str:
        if bars:
            last = bars[-1]
            signature = {
                "symbol": last.symbol,
                "timeframe": last.timeframe,
                "len": len(bars),
                "last_ts": last.timestamp_close.astimezone(UTC).isoformat(),
                "last_close": last.close,
            }
        else:
            signature = {
                "symbol": "",
                "timeframe": "",
                "len": 0,
                "last_ts": "",
                "last_close": 0.0,
            }

        param_key = json.dumps(params, sort_keys=True, default=str)
        return (
            f"{signature['symbol']}|{signature['timeframe']}|{normalized_id}|"
            f"{signature['len']}|{signature['last_ts']}|{signature['last_close']}|"
            f"{self._backend.backend_name}|{param_key}"
        )

    @staticmethod
    def _spec_key(spec: dict[str, object]) -> str:
        explicit = spec.get("key")
        if isinstance(explicit, str) and explicit:
            return explicit
        identifier = str(spec["id"])
        raw_params = spec.get("params", {})
        params = {str(key): value for key, value in raw_params.items()} if isinstance(raw_params, dict) else {}
        if not params:
            return identifier
        flat = "_".join(f"{key}_{params[key]}" for key in sorted(params))
        return f"{identifier}_{flat}"
