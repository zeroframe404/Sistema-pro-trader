from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from core.config_models import RegimeConfig
from core.event_bus import EventBus
from core.event_types import EventType
from core.events import BarCloseEvent, RegimeChangeEvent
from data.asset_types import AssetClass
from data.models import Tick
from indicators.indicator_engine import IndicatorEngine
from regime.market_conditions import MarketConditionsChecker
from regime.news_window_detector import EconomicEvent, NewsWindowDetector
from regime.regime_detector import RegimeDetector
from regime.regime_models import LiquidityRegime, MarketRegime, TrendRegime, VolatilityRegime
from tests.unit._indicator_fixtures import make_bars


class _RepoStub:
    def __init__(self, bars):
        self._bars = bars

    async def get_ohlcv(self, **kwargs):  # type: ignore[no-untyped-def]
        return list(self._bars)


@pytest.mark.asyncio
async def test_regime_detector_pipeline_detects_real_data() -> None:
    bars = make_bars([1.0 + i * 0.001 for i in range(220)], timeframe="H1")
    detector = RegimeDetector(indicator_engine=IndicatorEngine())
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
    assert regime.symbol == "EURUSD"
    assert regime.timeframe == "H1"


@pytest.mark.asyncio
async def test_regime_change_event_published_on_state_change(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = make_bars([1.0 + i * 0.001 for i in range(220)], timeframe="H1")
    repo = _RepoStub(bars)
    bus = EventBus()
    await bus.start()

    detector = RegimeDetector(
        indicator_engine=IndicatorEngine(data_repository=repo),
        data_repository=repo,
        event_bus=bus,
        config=RegimeConfig(min_bars_for_detection=50, regime_change_cooldown_bars=0),
        run_id="run-regime",
    )

    changes: list[RegimeChangeEvent] = []
    changed_event = asyncio.Event()

    @bus.subscribe(EventType.REGIME_CHANGE)
    async def _on_change(event) -> None:  # type: ignore[no-untyped-def]
        if isinstance(event, RegimeChangeEvent):
            changes.append(event)
            changed_event.set()

    first = bars[-2]
    second = bars[-1]

    first_result = MarketRegime(
        symbol="EURUSD",
        timeframe="H1",
        timestamp=first.timestamp_close,
        trend=TrendRegime.RANGING,
        volatility=VolatilityRegime.LOW,
        liquidity=LiquidityRegime.LIQUID,
        is_tradeable=True,
        no_trade_reasons=[],
        confidence=0.7,
        recommended_strategies=["mean_reversion"],
        description="first",
        metrics={},
    )
    second_result = first_result.model_copy(
        update={
            "timestamp": second.timestamp_close,
            "trend": TrendRegime.STRONG_UPTREND,
            "description": "second",
        }
    )

    calls = {"n": 0}

    async def fake_detect(_bars, current_tick=None):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return first_result if calls["n"] == 1 else second_result

    monkeypatch.setattr(detector, "detect", fake_detect)

    for bar in [first, second]:
        event = BarCloseEvent(
            source="test",
            run_id="run-regime",
            symbol=bar.symbol,
            broker=bar.broker,
            timeframe=bar.timeframe,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            timestamp_open=bar.timestamp_open,
            timestamp_close=bar.timestamp_close,
            timestamp=bar.timestamp_close,
        )
        await detector.detect_on_bar_close(event)

    await asyncio.wait_for(changed_event.wait(), timeout=1)
    assert len(changes) == 1
    assert changes[0].previous_regime == TrendRegime.RANGING.value
    assert changes[0].new_regime == TrendRegime.STRONG_UPTREND.value
    await bus.stop()


@pytest.mark.asyncio
async def test_news_window_detector_blocks_when_event_in_window() -> None:
    detector = NewsWindowDetector()
    now = datetime.now(UTC)
    detector._events = [  # noqa: SLF001
        EconomicEvent(
            event_id="ev1",
            title="Test Event",
            country="US",
            currency="USD",
            scheduled_at=now + timedelta(minutes=5),
            impact="high",
            affected_assets=["EURUSD"],
            source="manual",
            actual=None,
            forecast=None,
            previous=None,
        )
    ]

    blocked, _ = detector.is_in_news_window("EURUSD", AssetClass.FOREX, now)
    assert blocked is True


@pytest.mark.asyncio
async def test_session_and_market_conditions_block_outside_session(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = make_bars([1.0 + i * 0.001 for i in range(200)], timeframe="H1")
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

    checker = MarketConditionsChecker()
    monkeypatch.setattr(checker._session_manager, "get_session_quality", lambda *args, **kwargs: 0.1)  # noqa: SLF001

    reasons = await checker.check("EURUSD", "mock", AssetClass.FOREX, tick, bars)
    assert "bad_session" in reasons

