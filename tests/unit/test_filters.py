from __future__ import annotations

from datetime import UTC, datetime

from data.asset_types import AssetClass
from regime.news_window_detector import EconomicEvent, NewsWindowDetector
from regime.regime_models import TrendRegime, VolatilityRegime
from signals.filters.correlation_filter import CorrelationFilter
from signals.filters.news_filter import NewsFilter
from signals.filters.regime_filter import RegimeFilter
from signals.filters.session_filter import SessionFilter
from signals.filters.spread_filter import SpreadFilter
from signals.signal_models import SignalDirection
from tests.unit._signal_fixtures import make_signal


def test_regime_filter_blocks_buy_in_strong_downtrend() -> None:
    signal = make_signal(direction=SignalDirection.BUY)
    signal.regime.trend = TrendRegime.STRONG_DOWNTREND
    result = RegimeFilter().apply(signal)
    assert not result.passed


def test_regime_filter_blocks_extreme_volatility() -> None:
    signal = make_signal(direction=SignalDirection.BUY)
    signal.regime.volatility = VolatilityRegime.EXTREME
    result = RegimeFilter().apply(signal)
    assert not result.passed


def test_regime_filter_reduces_trend_following_in_ranging() -> None:
    signal = make_signal(strategy_id="trend_following")
    signal.regime.trend = TrendRegime.RANGING
    result = RegimeFilter().apply(signal)
    assert result.passed
    assert result.confidence_multiplier < 1.0


def test_news_filter_blocks_in_news_window() -> None:
    detector = NewsWindowDetector()
    detector._events = [  # noqa: SLF001
        EconomicEvent(
            event_id="NFP",
            title="NFP",
            country="US",
            currency="USD",
            scheduled_at=datetime.now(UTC),
            impact="high",
            affected_assets=["EURUSD"],
        )
    ]
    signal = make_signal(symbol="EURUSD")
    result = NewsFilter(detector).apply(signal, AssetClass.FOREX)
    assert not result.passed
    assert "news_window_NFP" in (result.reason or "")


def test_session_filter_blocks_forex_outside_session() -> None:
    signal = make_signal(symbol="EURUSD").model_copy(update={"timestamp": datetime(2026, 1, 1, 23, 30, tzinfo=UTC)})
    signal.metadata["asset_class"] = AssetClass.FOREX.value
    result = SessionFilter().apply(signal)
    assert not result.passed


def test_session_filter_allows_crypto_247() -> None:
    signal = make_signal(symbol="BTCUSDT").model_copy(update={"timestamp": datetime(2026, 1, 1, 23, 30, tzinfo=UTC)})
    signal.metadata["asset_class"] = AssetClass.CRYPTO.value
    result = SessionFilter().apply(signal)
    assert result.passed


def test_correlation_filter_blocks_third_usd_signal() -> None:
    filt = CorrelationFilter(window_minutes=60, group_limit=2)
    first = make_signal(symbol="EURUSD")
    second = make_signal(symbol="GBPUSD")
    third = make_signal(symbol="USDJPY")
    assert filt.apply(first).passed
    filt.register(first)
    assert filt.apply(second).passed
    filt.register(second)
    blocked = filt.apply(third)
    assert not blocked.passed


def test_spread_filter_blocks_spike() -> None:
    signal = make_signal(symbol="EURUSD")
    result = SpreadFilter(max_multiplier=3.0).apply(signal, current_spread=0.0005, average_spread=0.0001)
    assert not result.passed
