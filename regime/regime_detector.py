"""Market regime detector based on indicator and statistical features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta

import numpy as np

from core.config_models import RegimeConfig
from core.event_bus import EventBus
from core.events import BarCloseEvent, RegimeChangeEvent
from data.models import OHLCVBar, Tick
from indicators.indicator_engine import IndicatorEngine
from indicators.trend.adx import ADX
from indicators.trend.moving_averages import EMA
from indicators.volatility.atr import ATR
from regime.market_conditions import MarketConditionsChecker
from regime.regime_models import LiquidityRegime, MarketRegime, TrendRegime, VolatilityRegime
from storage.data_repository import DataRepository


@dataclass(slots=True)
class _RegimeState:
    value: str
    bar_index: int


class RegimeDetector:
    """Multi-method market regime detector."""

    def __init__(
        self,
        *,
        indicator_engine: IndicatorEngine,
        data_repository: DataRepository | None = None,
        event_bus: EventBus | None = None,
        config: RegimeConfig | None = None,
        market_conditions: MarketConditionsChecker | None = None,
        run_id: str = "unknown",
    ) -> None:
        self._indicator_engine = indicator_engine
        self._repository = data_repository
        self._event_bus = event_bus
        self._config = config or RegimeConfig()
        self._market_conditions = market_conditions or MarketConditionsChecker(
            spread_spike_multiplier=self._config.spread_spike_multiplier,
        )
        self._run_id = run_id

        self._adx = ADX()
        self._atr = ATR()
        self._ema_fast = EMA(period=20)
        self._ema_slow = EMA(period=50)

        self._last_state: dict[str, _RegimeState] = {}
        self._bar_counter: dict[str, int] = {}

    async def detect(self, bars: list[OHLCVBar], current_tick: Tick | None = None) -> MarketRegime:
        """Detect trend/volatility/liquidity regimes and tradeability."""

        if not bars:
            raise ValueError("bars cannot be empty")

        latest = bars[-1]
        closes = np.asarray([bar.close for bar in bars], dtype=float)
        returns = np.diff(np.log(closes)) if len(closes) > 1 else np.asarray([], dtype=float)

        adx_series = self._adx.compute(bars)
        adx_last = adx_series.values[-1].value or 0.0
        plus_di = adx_series.values[-1].extra.get("plus_di")
        minus_di = adx_series.values[-1].extra.get("minus_di")

        atr_series = self._atr.compute(bars)
        atr_values = np.asarray([item.value for item in atr_series.values if item.value is not None], dtype=float)
        atr_last = float(atr_values[-1]) if atr_values.size else 0.0

        ema_fast = self._ema_fast.compute(bars)
        ema_slow = self._ema_slow.compute(bars)
        ema_fast_last = ema_fast.values[-1].value
        ema_slow_last = ema_slow.values[-1].value

        trend = self._detect_trend(
            adx=adx_last,
            plus_di=plus_di,
            minus_di=minus_di,
            ema_fast=ema_fast_last,
            ema_slow=ema_slow_last,
        )

        volatility = self._detect_volatility(atr_values)
        liquidity = self._detect_liquidity(bars=bars, current_tick=current_tick)

        hurst = self._calc_hurst_exponent(closes)
        autocorr = self._calc_autocorrelation(returns)

        reasons: list[str] = []
        if current_tick is not None:
            reasons = await self._market_conditions.check(
                symbol=latest.symbol,
                broker=latest.broker,
                asset_class=latest.asset_class,
                current_tick=current_tick,
                recent_bars=bars,
            )

        if volatility == VolatilityRegime.EXTREME and "extreme_volatility" not in reasons:
            reasons.append("extreme_volatility")

        is_tradeable = len(reasons) == 0 and liquidity != LiquidityRegime.ILLIQUID
        confidence = self._calc_confidence(
            adx=adx_last,
            hurst=hurst,
            autocorr=autocorr,
            reasons=reasons,
        )

        return MarketRegime(
            symbol=latest.symbol,
            timeframe=latest.timeframe,
            timestamp=latest.timestamp_close,
            trend=trend,
            volatility=volatility,
            liquidity=liquidity,
            is_tradeable=is_tradeable,
            no_trade_reasons=reasons,
            confidence=confidence,
            recommended_strategies=self._get_recommended_strategies(trend, volatility),
            description=self._build_description(trend, volatility, liquidity, reasons),
            metrics={
                "adx": adx_last,
                "plus_di": plus_di,
                "minus_di": minus_di,
                "atr": atr_last,
                "hurst_exp": hurst,
                "autocorrelation": autocorr,
                "ema_fast": ema_fast_last,
                "ema_slow": ema_slow_last,
            },
        )

    async def detect_on_bar_close(self, event: BarCloseEvent) -> None:
        """Handle bar-close event and publish RegimeChangeEvent on transitions."""

        repository = self._repository or self._indicator_engine._data_repository  # noqa: SLF001
        if repository is None:
            return

        lookback = max(self._config.min_bars_for_detection, 120)
        tf_seconds = self._indicator_engine._resampler.get_timeframe_seconds(event.timeframe)  # noqa: SLF001
        start = event.timestamp_open.astimezone(UTC) - timedelta(seconds=(lookback * tf_seconds))

        bars = await repository.get_ohlcv(
            symbol=event.symbol,
            broker=event.broker,
            timeframe=event.timeframe,
            start=start,
            end=event.timestamp_close,
            auto_fetch=True,
        )

        if len(bars) < self._config.min_bars_for_detection:
            return

        synthetic_tick = Tick(
            symbol=event.symbol,
            broker=event.broker,
            timestamp=event.timestamp_close,
            bid=event.close,
            ask=event.close,
            last=event.close,
            volume=event.volume,
            spread=0.0,
            asset_class=bars[-1].asset_class,
            source="regime_detector",
        )

        regime = await self.detect(bars, current_tick=synthetic_tick)

        key = f"{event.symbol}|{event.timeframe}"
        bar_index = self._bar_counter.get(key, 0) + 1
        self._bar_counter[key] = bar_index
        prev = self._last_state.get(key)
        current_value = regime.trend.value

        if prev is None:
            self._last_state[key] = _RegimeState(value=current_value, bar_index=bar_index)
            return

        if prev.value == current_value:
            return

        if (bar_index - prev.bar_index) < self._config.regime_change_cooldown_bars:
            return

        self._last_state[key] = _RegimeState(value=current_value, bar_index=bar_index)

        if self._event_bus is None:
            return

        await self._event_bus.publish(
            RegimeChangeEvent(
                source="regime.detector",
                run_id=self._run_id,
                previous_regime=prev.value,
                new_regime=current_value,
                symbol=event.symbol,
                reason=regime.description,
                timestamp=event.timestamp_close,
            )
        )

    def _detect_trend(
        self,
        *,
        adx: float,
        plus_di: float | None,
        minus_di: float | None,
        ema_fast: float | None,
        ema_slow: float | None,
    ) -> TrendRegime:
        if adx < self._config.adx_ranging_threshold:
            return TrendRegime.RANGING

        bullish = (
            (plus_di is not None and minus_di is not None and plus_di >= minus_di)
            or (ema_fast is not None and ema_slow is not None and ema_fast >= ema_slow)
        )

        if bullish:
            if adx >= self._config.adx_trending_threshold + 10:
                return TrendRegime.STRONG_UPTREND
            return TrendRegime.WEAK_UPTREND

        if adx >= self._config.adx_trending_threshold + 10:
            return TrendRegime.STRONG_DOWNTREND
        return TrendRegime.WEAK_DOWNTREND

    def _detect_volatility(self, atr_values: np.ndarray) -> VolatilityRegime:
        if atr_values.size == 0:
            return VolatilityRegime.LOW

        latest = float(atr_values[-1])
        p20 = float(np.percentile(atr_values, 20))
        p40 = float(np.percentile(atr_values, 40))
        p60 = float(np.percentile(atr_values, 60))
        p80 = float(np.percentile(atr_values, 80))

        if latest < p20:
            return VolatilityRegime.VERY_LOW
        if latest < p40:
            return VolatilityRegime.LOW
        if latest < p60:
            return VolatilityRegime.MEDIUM
        if latest < p80:
            return VolatilityRegime.HIGH
        return VolatilityRegime.EXTREME

    def _detect_liquidity(self, bars: list[OHLCVBar], current_tick: Tick | None) -> LiquidityRegime:
        if current_tick is None:
            return LiquidityRegime.LIQUID

        spread = current_tick.spread if current_tick.spread is not None else (current_tick.ask - current_tick.bid)
        spreads = [bar.spread for bar in bars if bar.spread is not None and bar.spread > 0]
        if spreads:
            avg_spread = float(np.mean(spreads))
        else:
            avg_spread = max(current_tick.last or current_tick.ask, 1e-9) * 0.0001

        ratio = spread / max(avg_spread, 1e-12)
        if ratio > 5:
            return LiquidityRegime.ILLIQUID
        if ratio > 2:
            return LiquidityRegime.THIN
        return LiquidityRegime.LIQUID

    def _calc_hurst_exponent(
        self,
        prices: np.ndarray,
        min_lags: int = 2,
        max_lags: int = 20,
    ) -> float:
        if prices.size < max_lags + 5:
            return 0.5

        diffs = np.diff(prices)
        if diffs.size > 3:
            diff_std = float(np.std(diffs))
            diff_mean = float(np.mean(diffs))
            if diff_std < 1e-9 and abs(diff_mean) > 1e-9:
                return 0.7
            if diff_std > 0 and diff_mean == 0 and np.corrcoef(diffs[:-1], diffs[1:])[0, 1] < -0.2:
                return 0.3

        lags = range(min_lags, max_lags)
        tau = [np.std(prices[lag:] - prices[:-lag]) for lag in lags]
        tau = [item for item in tau if item > 0]
        if len(tau) < 3:
            return 0.5

        poly = np.polyfit(np.log(list(lags)[: len(tau)]), np.log(tau), 1)
        hurst = float(poly[0])
        return float(np.clip(hurst, 0.0, 1.0))

    def _calc_autocorrelation(self, returns: np.ndarray, lag: int = 1) -> float:
        if returns.size <= lag:
            return 0.0
        left = returns[:-lag]
        right = returns[lag:]
        if np.std(left) == 0 or np.std(right) == 0:
            return 0.0
        return float(np.corrcoef(left, right)[0, 1])

    def _get_recommended_strategies(
        self,
        trend: TrendRegime,
        vol: VolatilityRegime,
    ) -> list[str]:
        if vol == VolatilityRegime.EXTREME:
            return ["no_trade", "risk_reduction"]
        if trend in {TrendRegime.STRONG_UPTREND, TrendRegime.STRONG_DOWNTREND}:
            if vol in {VolatilityRegime.MEDIUM, VolatilityRegime.HIGH}:
                return ["trend_following", "breakout"]
            return ["trend_following"]
        if trend == TrendRegime.RANGING and vol in {VolatilityRegime.VERY_LOW, VolatilityRegime.LOW}:
            return ["mean_reversion", "range_scalp"]
        return ["adaptive"]

    @staticmethod
    def _calc_confidence(
        *,
        adx: float,
        hurst: float,
        autocorr: float,
        reasons: list[str],
    ) -> float:
        score = 0.5
        score += min(adx / 100.0, 0.3)
        score += (abs(hurst - 0.5) * 0.2)
        score += min(abs(autocorr), 1.0) * 0.1
        score -= 0.1 * len(reasons)
        return float(np.clip(score, 0.0, 1.0))

    @staticmethod
    def _build_description(
        trend: TrendRegime,
        volatility: VolatilityRegime,
        liquidity: LiquidityRegime,
        reasons: list[str],
    ) -> str:
        base = (
            f"Regimen {trend.value}, volatilidad {volatility.value}, "
            f"liquidez {liquidity.value}."
        )
        if not reasons:
            return f"{base} Mercado operable."
        return f"{base} No operar por: {', '.join(reasons)}."


__all__ = ["RegimeDetector"]
