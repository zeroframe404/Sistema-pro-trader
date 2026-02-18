"""Shared helper functions for indicator implementations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from data.models import OHLCVBar
from indicators.indicator_result import IndicatorSeries, IndicatorValue


def get_price_series(frame: pd.DataFrame, price_field: str) -> np.ndarray:
    """Select one price field from OHLCV dataframe."""

    field = price_field.lower()
    if field in {"open", "high", "low", "close"}:
        return np.asarray(frame[field].to_numpy(dtype=float), dtype=float)
    if field == "hl2":
        return np.asarray(((frame["high"] + frame["low"]) / 2.0).to_numpy(dtype=float), dtype=float)
    if field == "hlc3":
        return np.asarray(
            ((frame["high"] + frame["low"] + frame["close"]) / 3.0).to_numpy(dtype=float),
            dtype=float,
        )
    if field == "ohlc4":
        return np.asarray(
            ((frame["open"] + frame["high"] + frame["low"] + frame["close"]) / 4.0).to_numpy(dtype=float),
            dtype=float,
        )
    raise ValueError(f"Unsupported price_field: {price_field}")


def param_int(params: dict[str, object], key: str, default: int) -> int:
    """Read integer parameter safely from dynamic params dict."""

    value = params.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def param_float(params: dict[str, object], key: str, default: float) -> float:
    """Read float parameter safely from dynamic params dict."""

    value = params.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def build_indicator_series(
    *,
    indicator_id: str,
    bars: list[OHLCVBar],
    values: np.ndarray,
    name: str,
    warmup_period: int,
    backend_used: str,
    parameters: dict[str, Any],
    extras: list[dict[str, Any]] | None = None,
) -> IndicatorSeries:
    """Convert numeric arrays into a normalized IndicatorSeries."""

    payload: list[IndicatorValue] = []
    extras_data = extras or [{} for _ in bars]

    for idx, bar in enumerate(bars):
        numeric = float(values[idx]) if idx < len(values) and np.isfinite(values[idx]) else None
        is_valid = numeric is not None and idx >= (warmup_period - 1)
        payload.append(
            IndicatorValue(
                name=name,
                value=numeric if is_valid else None,
                timestamp=bar.timestamp_close.astimezone(UTC),
                is_valid=is_valid,
                extra=extras_data[idx] if idx < len(extras_data) else {},
            )
        )

    return IndicatorSeries(
        indicator_id=indicator_id,
        symbol=bars[-1].symbol if bars else "",
        timeframe=bars[-1].timeframe if bars else "",
        values=payload,
        warmup_period=warmup_period,
        computed_at=datetime.now(UTC),
        parameters=parameters,
        backend_used=backend_used,
    )


def empty_series(
    *,
    indicator_id: str,
    bars: list[OHLCVBar],
    name: str,
    warmup_period: int,
    backend_used: str,
    parameters: dict[str, Any],
) -> IndicatorSeries:
    """Build an all-invalid series for short inputs."""

    values = np.full((len(bars),), np.nan, dtype=float)
    return build_indicator_series(
        indicator_id=indicator_id,
        bars=bars,
        values=values,
        name=name,
        warmup_period=warmup_period,
        backend_used=backend_used,
        parameters=parameters,
    )
