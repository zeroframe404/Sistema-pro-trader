from __future__ import annotations

import pytest

from data.asset_types import AssetClass
from data.models import Tick
from indicators.indicator_engine import IndicatorEngine
from indicators.indicator_result import IndicatorSeries, IndicatorValue
from regime.regime_detector import RegimeDetector
from regime.regime_models import TrendRegime, VolatilityRegime
from tests.unit._indicator_fixtures import make_bars


def _series(name: str, values: list[float], extras: list[dict] | None = None) -> IndicatorSeries:
    bars = make_bars([1.0 + i * 0.01 for i in range(len(values))])
    payload = []
    extras = extras or [{} for _ in values]
    for idx, value in enumerate(values):
        payload.append(
            IndicatorValue(
                name=name,
                value=value,
                timestamp=bars[idx].timestamp_close,
                is_valid=True,
                extra=extras[idx],
            )
        )
    return IndicatorSeries(
        indicator_id=name,
        symbol="EURUSD",
        timeframe="M1",
        values=payload,
        warmup_period=1,
        parameters={},
        backend_used="custom",
    )


@pytest.mark.asyncio
async def test_detect_strong_uptrend_with_high_adx(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = make_bars([1.0 + i * 0.01 for i in range(150)])
    detector = RegimeDetector(indicator_engine=IndicatorEngine())

    monkeypatch.setattr(detector._adx, "compute", lambda _bars: _series("ADX", [35.0] * len(_bars), [{"plus_di": 30.0, "minus_di": 10.0}] * len(_bars)))
    monkeypatch.setattr(detector._atr, "compute", lambda _bars: _series("ATR", [0.01 + i * 0.0001 for i in range(len(_bars))]))
    monkeypatch.setattr(detector._ema_fast, "compute", lambda _bars: _series("EMA", [1.5] * len(_bars)))
    monkeypatch.setattr(detector._ema_slow, "compute", lambda _bars: _series("EMA", [1.0] * len(_bars)))

    tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=bars[-1].timestamp_close,
        bid=bars[-1].close,
        ask=bars[-1].close + 0.0001,
        last=bars[-1].close,
        volume=100,
        spread=0.0001,
        asset_class=AssetClass.FOREX,
        source="test",
    )

    regime = await detector.detect(bars, current_tick=tick)
    assert regime.trend == TrendRegime.STRONG_UPTREND


@pytest.mark.asyncio
async def test_detect_ranging_with_low_adx(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = make_bars([1.0 + ((-1) ** i) * 0.001 for i in range(150)])
    detector = RegimeDetector(indicator_engine=IndicatorEngine())

    monkeypatch.setattr(detector._adx, "compute", lambda _bars: _series("ADX", [15.0] * len(_bars), [{"plus_di": 10.0, "minus_di": 11.0}] * len(_bars)))
    monkeypatch.setattr(detector._atr, "compute", lambda _bars: _series("ATR", [0.01 + i * 0.0001 for i in range(len(_bars))]))
    monkeypatch.setattr(detector._ema_fast, "compute", lambda _bars: _series("EMA", [1.0] * len(_bars)))
    monkeypatch.setattr(detector._ema_slow, "compute", lambda _bars: _series("EMA", [1.0] * len(_bars)))

    tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=bars[-1].timestamp_close,
        bid=bars[-1].close,
        ask=bars[-1].close + 0.0001,
        last=bars[-1].close,
        volume=100,
        spread=0.0001,
        asset_class=AssetClass.FOREX,
        source="test",
    )

    regime = await detector.detect(bars, current_tick=tick)
    assert regime.trend == TrendRegime.RANGING


def test_hurst_exponent_detects_trending_vs_mean_reverting() -> None:
    detector = RegimeDetector(indicator_engine=IndicatorEngine())
    trend_prices = __import__("numpy").cumsum(__import__("numpy").ones(300))
    mr_prices = __import__("numpy").array([(-1) ** i for i in range(300)], dtype=float)

    h_trend = detector._calc_hurst_exponent(trend_prices)
    h_mr = detector._calc_hurst_exponent(mr_prices)

    assert h_trend > 0.6
    assert h_mr < 0.6


@pytest.mark.asyncio
async def test_spread_spike_sets_no_trade_reason() -> None:
    bars = make_bars([1.0 + i * 0.005 for i in range(200)])
    detector = RegimeDetector(indicator_engine=IndicatorEngine())

    tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=bars[-1].timestamp_close,
        bid=bars[-1].close,
        ask=bars[-1].close + 0.01,
        last=bars[-1].close,
        volume=100,
        spread=0.01,
        asset_class=AssetClass.FOREX,
        source="test",
    )

    regime = await detector.detect(bars, current_tick=tick)
    assert regime.is_tradeable is False
    assert "spread_spike" in regime.no_trade_reasons


@pytest.mark.asyncio
async def test_extreme_volatility_regime(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = make_bars([1.0 + i * 0.01 for i in range(200)])
    detector = RegimeDetector(indicator_engine=IndicatorEngine())

    atr_values = [0.01] * 199 + [10.0]
    monkeypatch.setattr(detector._atr, "compute", lambda _bars: _series("ATR", atr_values))
    monkeypatch.setattr(detector._adx, "compute", lambda _bars: _series("ADX", [20.0] * len(_bars), [{"plus_di": 20.0, "minus_di": 20.0}] * len(_bars)))
    monkeypatch.setattr(detector._ema_fast, "compute", lambda _bars: _series("EMA", [1.0] * len(_bars)))
    monkeypatch.setattr(detector._ema_slow, "compute", lambda _bars: _series("EMA", [1.0] * len(_bars)))

    tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=bars[-1].timestamp_close,
        bid=bars[-1].close,
        ask=bars[-1].close + 0.0001,
        last=bars[-1].close,
        volume=100,
        spread=0.0001,
        asset_class=AssetClass.FOREX,
        source="test",
    )

    regime = await detector.detect(bars, current_tick=tick)
    assert regime.volatility == VolatilityRegime.EXTREME
