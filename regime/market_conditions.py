"""Operational market condition checks for tradeability."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from data.asset_types import AssetClass
from data.models import OHLCVBar, Tick
from indicators.volatility.atr import ATR
from regime.news_window_detector import NewsWindowDetector
from regime.session_manager import SessionManager


class MarketConditionsChecker:
    """Evaluate if market conditions allow trading."""

    def __init__(
        self,
        *,
        session_manager: SessionManager | None = None,
        news_detector: NewsWindowDetector | None = None,
        spread_spike_multiplier: float = 3.0,
    ) -> None:
        self._session_manager = session_manager or SessionManager()
        self._news_detector = news_detector or NewsWindowDetector()
        self._spread_spike_multiplier = spread_spike_multiplier
        self._atr = ATR()

    async def check(
        self,
        symbol: str,
        broker: str,
        asset_class: AssetClass,
        current_tick: Tick,
        recent_bars: list[OHLCVBar],
    ) -> list[str]:
        """Return blocking reasons for the current market state."""

        _ = broker
        reasons: list[str] = []

        if self._has_spread_spike(current_tick, recent_bars):
            reasons.append("spread_spike")

        if self._is_low_volume(recent_bars):
            reasons.append("low_volume")

        quality = self._session_manager.get_session_quality(symbol, asset_class, datetime.now(UTC))
        if asset_class != AssetClass.CRYPTO and quality < 0.4:
            reasons.append("bad_session")

        in_news, _event = self._news_detector.is_in_news_window(
            symbol=symbol,
            asset_class=asset_class,
            now=datetime.now(UTC),
        )
        if in_news:
            reasons.append("news_window")

        if self._is_price_frozen(current_tick, recent_bars):
            reasons.append("price_freeze")

        if self._is_extreme_volatility(recent_bars):
            reasons.append("extreme_volatility")

        return reasons

    def _has_spread_spike(self, tick: Tick, bars: list[OHLCVBar]) -> bool:
        spread = tick.spread if tick.spread is not None else (tick.ask - tick.bid)
        spreads = [bar.spread for bar in bars if bar.spread is not None and bar.spread > 0]
        if not spreads:
            reference = max(tick.last or tick.ask, 1e-9) * 0.0002
        else:
            reference = float(np.mean(spreads))
        return spread > (reference * self._spread_spike_multiplier)

    @staticmethod
    def _is_low_volume(bars: list[OHLCVBar]) -> bool:
        if len(bars) < 20:
            return False
        volumes = np.asarray([bar.volume for bar in bars], dtype=float)
        p5 = float(np.percentile(volumes, 5))
        return float(volumes[-1]) <= p5

    @staticmethod
    def _is_price_frozen(tick: Tick, bars: list[OHLCVBar]) -> bool:
        if len(bars) < 5:
            return False
        recent = [bar.close for bar in bars[-5:]]
        if max(recent) - min(recent) <= 1e-10:
            return True
        if tick.last is not None and abs(tick.last - recent[-1]) <= 1e-10:
            # Tick equals last close while bars are static.
            return (max(recent) - min(recent)) <= 1e-6
        return False

    def _is_extreme_volatility(self, bars: list[OHLCVBar]) -> bool:
        if len(bars) < 30:
            return False
        regime = self._atr.volatility_regime(bars)
        return regime == "extreme"


__all__ = ["MarketConditionsChecker"]
