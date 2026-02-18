from __future__ import annotations

import pytest

from core.events import BarCloseEvent
from indicators.indicator_engine import IndicatorEngine
from tests.unit._indicator_fixtures import make_bars


class _RepoStub:
    def __init__(self, bars):
        self._bars = bars
        self.calls = 0

    async def get_ohlcv(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return list(self._bars)


@pytest.mark.asyncio
async def test_compute_uses_cache_on_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = make_bars([1.0 + i * 0.01 for i in range(80)])
    engine = IndicatorEngine(cache_enabled=True, cache_ttl_seconds=60)

    indicator = engine._make_indicator("EMA")  # noqa: SLF001
    counter = {"calls": 0}
    original = indicator.compute

    def wrapped_compute(*args, **kwargs):  # type: ignore[no-untyped-def]
        counter["calls"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(indicator, "compute", wrapped_compute)
    monkeypatch.setattr(engine, "_make_indicator", lambda _id: indicator)

    await engine.compute("EMA", bars, period=20)
    await engine.compute("EMA", bars, period=20)

    assert counter["calls"] == 1


@pytest.mark.asyncio
async def test_invalidate_cache_removes_entries() -> None:
    bars = make_bars([1.0 + i * 0.01 for i in range(80)])
    engine = IndicatorEngine(cache_enabled=True, cache_ttl_seconds=60)

    await engine.compute("EMA", bars, period=20)
    assert engine._cache  # noqa: SLF001

    engine.invalidate_cache("EURUSD", "M1")
    assert not engine._cache  # noqa: SLF001


def test_dependency_order_atr_before_supertrend() -> None:
    engine = IndicatorEngine()
    order = engine.get_dependency_order(["SuperTrend", "RSI"])
    assert order.index("ATR") < order.index("SUPERTREND")


@pytest.mark.asyncio
async def test_compute_for_bar_uses_repository() -> None:
    bars = make_bars([1.0 + i * 0.01 for i in range(120)], timeframe="H1")
    repo = _RepoStub(bars)
    engine = IndicatorEngine(data_repository=repo, max_lookback_bars=300)

    last = bars[-1]
    event = BarCloseEvent(
        source="test",
        run_id="run-id",
        symbol=last.symbol,
        broker=last.broker,
        timeframe=last.timeframe,
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        volume=last.volume,
        timestamp_open=last.timestamp_open,
        timestamp_close=last.timestamp_close,
        timestamp=last.timestamp_close,
    )

    result = await engine.compute_for_bar(event, indicators=[{"id": "RSI", "params": {"period": 14}}])
    assert repo.calls == 1
    assert result


@pytest.mark.asyncio
async def test_fallback_without_talib_uses_other_backend() -> None:
    bars = make_bars([1.0 + i * 0.01 for i in range(80)])
    engine = IndicatorEngine(backend_preference="talib")
    series = await engine.compute("EMA", bars, period=20)

    assert series.backend_used in {"talib", "pandas_ta", "ta", "custom"}
    assert series.values[-1].value is not None
