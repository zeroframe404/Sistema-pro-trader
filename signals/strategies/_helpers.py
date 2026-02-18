"""Shared helper functions for built-in signal strategies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from regime.regime_models import MarketRegime
from signals.signal_models import Signal, SignalDirection, SignalReason, SignalStrength


def confidence_to_strength(confidence: float) -> SignalStrength:
    if confidence >= 0.75:
        return SignalStrength.STRONG
    if confidence >= 0.55:
        return SignalStrength.MODERATE
    if confidence >= 0.40:
        return SignalStrength.WEAK
    return SignalStrength.NONE


def build_signal(
    *,
    strategy_id: str,
    strategy_version: str,
    symbol: str,
    broker: str,
    timeframe: str,
    run_id: str,
    direction: SignalDirection,
    raw_score: float,
    confidence: float,
    reasons: list[SignalReason],
    regime: MarketRegime,
    horizon: str,
    price: float | None,
    timestamp: datetime,
    expiry_minutes: int = 120,
) -> Signal:
    return Signal(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        symbol=symbol,
        broker=broker,
        timeframe=timeframe,
        timestamp=timestamp.astimezone(UTC),
        run_id=run_id,
        direction=direction,
        strength=confidence_to_strength(confidence),
        raw_score=raw_score,
        confidence=max(0.0, min(confidence, 1.0)),
        reasons=reasons,
        regime=regime,
        horizon=horizon,
        entry_price=price,
        expires_at=(timestamp.astimezone(UTC) + timedelta(minutes=expiry_minutes)),
    )


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2 / (period + 1)
    current = values[0]
    for value in values[1:]:
        current = alpha * value + (1 - alpha) * current
    return float(current)


def sma(values: list[float], period: int) -> float:
    if len(values) < period or period <= 0:
        return float(np.mean(values)) if values else 0.0
    return float(np.mean(values[-period:]))


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        return 50.0
    deltas = np.diff(np.asarray(values, dtype=float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def bollinger_percent_b(values: list[float], period: int = 20, std_dev: float = 2.0) -> float:
    if len(values) < period:
        return 0.5
    window = np.asarray(values[-period:], dtype=float)
    mean = float(window.mean())
    std = float(window.std(ddof=0))
    upper = mean + std_dev * std
    lower = mean - std_dev * std
    if upper == lower:
        return 0.5
    return float((values[-1] - lower) / (upper - lower))


def stochastic_k(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(closes) < period:
        return 50.0
    high = max(highs[-period:])
    low = min(lows[-period:])
    if high == low:
        return 50.0
    return float(((closes[-1] - low) / (high - low)) * 100)


def trend_slope(values: list[float], period: int = 20) -> float:
    if len(values) < period:
        return 0.0
    y = np.asarray(values[-period:], dtype=float)
    x = np.arange(len(y), dtype=float)
    slope, _ = np.polyfit(x, y, deg=1)
    return float(slope)
