"""Stop-loss, take-profit, trailing, and time-exit logic."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from core.config_models import StopConfig, TimeExitConfig, TrailingConfig, TrailingStopMethod
from data.models import AssetInfo
from execution.order_models import Position
from regime.regime_models import MarketRegime
from risk.risk_models import OrderSide


class StopManager:
    """Calculate deterministic stops and exits for a position."""

    def calculate_stops(
        self,
        symbol: str,
        side: OrderSide,
        entry_price: float,
        atr: float,
        asset_info: AssetInfo,
        config: StopConfig,
        support_resistance: Sequence[float] | None = None,
        regime: MarketRegime | None = None,
    ) -> tuple[float, float, float | None]:
        """Return stop loss, take profit, and optional trailing distance."""

        _ = (symbol, regime)
        atr = max(atr, entry_price * 0.0001)
        pip_size = max(float(asset_info.pip_size or 0.0001), 1e-12)

        sl_method = config.default_sl_method.value
        if sl_method == "fixed_pips":
            distance = max(config.atr_multiplier_sl, 1.0) * pip_size
            stop_loss = entry_price - distance if side == OrderSide.BUY else entry_price + distance
        elif sl_method == "percent":
            distance = entry_price * (config.atr_multiplier_sl / 100.0)
            stop_loss = entry_price - distance if side == OrderSide.BUY else entry_price + distance
        elif sl_method == "support_resistance" and support_resistance:
            stop_loss = self._sl_from_support_resistance(side, entry_price, list(support_resistance), pip_size)
        elif sl_method == "chandelier" and support_resistance:
            extremes = list(support_resistance)
            if side == OrderSide.BUY:
                stop_loss = min(extremes) - (atr * config.atr_multiplier_sl)
            else:
                stop_loss = max(extremes) + (atr * config.atr_multiplier_sl)
        else:
            distance = atr * config.atr_multiplier_sl
            stop_loss = entry_price - distance if side == OrderSide.BUY else entry_price + distance

        tp_method = config.default_tp_method.value
        if tp_method == "fixed_pips":
            tp_distance = abs(entry_price - stop_loss)
            take_profit = entry_price + tp_distance if side == OrderSide.BUY else entry_price - tp_distance
        elif tp_method == "support_resistance" and support_resistance:
            take_profit = self._tp_from_support_resistance(side, entry_price, list(support_resistance), atr)
        elif tp_method == "atr_based":
            tp_distance = atr * max(config.min_rr_ratio, 1.0)
            take_profit = entry_price + tp_distance if side == OrderSide.BUY else entry_price - tp_distance
        else:
            rr_ratio = max(config.min_rr_ratio, 0.1)
            sl_distance = abs(entry_price - stop_loss)
            tp_distance = sl_distance * rr_ratio
            take_profit = entry_price + tp_distance if side == OrderSide.BUY else entry_price - tp_distance

        trailing_distance = None
        if config.trailing_stop_enabled:
            if config.trailing_stop_method == TrailingStopMethod.ATR_BASED:
                trailing_distance = atr * config.trailing_atr_multiplier
            else:
                trailing_distance = abs(entry_price - stop_loss)

        return (float(stop_loss), float(take_profit), float(trailing_distance) if trailing_distance is not None else None)

    def should_trail(
        self,
        position: Position,
        current_price: float,
        atr: float,
        config: TrailingConfig,
    ) -> float | None:
        """Return updated stop-loss if trailing should move, otherwise None."""

        if position.stop_loss is None:
            return None
        atr = max(atr, position.entry_price * 0.001)
        pip_size = max(float(position.metadata.get("pip_size", 0.0001)), 1e-12)

        if config.method == TrailingStopMethod.FIXED_DISTANCE:
            distance = config.fixed_distance_pips * pip_size
            candidate = current_price - distance if position.side == OrderSide.BUY else current_price + distance
        elif config.method == TrailingStopMethod.BREAKEVEN:
            initial_r = abs(position.entry_price - position.stop_loss)
            if initial_r <= 0:
                return None
            move = (current_price - position.entry_price) if position.side == OrderSide.BUY else (position.entry_price - current_price)
            if move >= initial_r * config.breakeven_r_multiple:
                candidate = position.entry_price
            else:
                return None
        elif config.method == TrailingStopMethod.STEP:
            initial_r = abs(position.entry_price - position.stop_loss)
            if initial_r <= 0:
                return None
            move = (current_price - position.entry_price) if position.side == OrderSide.BUY else (position.entry_price - current_price)
            steps = int(move / max(initial_r * config.step_r_multiple, 1e-12))
            if steps <= 0:
                return None
            delta = steps * initial_r * config.step_r_multiple
            candidate = position.entry_price + delta if position.side == OrderSide.BUY else position.entry_price - delta
        else:
            distance = atr * config.atr_multiplier
            candidate = current_price - distance if position.side == OrderSide.BUY else current_price + distance

        if position.side == OrderSide.BUY:
            if candidate <= position.stop_loss:
                return None
            return float(candidate)
        if candidate >= position.stop_loss:
            return None
        return float(candidate)

    def should_exit_by_time(
        self,
        position: Position,
        current_time: datetime,
        config: TimeExitConfig,
    ) -> tuple[bool, str]:
        """Return whether a position should be closed due to time rules."""

        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=UTC)
        timeframe = str(position.metadata.get("timeframe", "H1"))
        bars_held = int(position.metadata.get("bars_held", 0))
        max_bars = config.max_hold_bars.get(timeframe)
        if max_bars is not None and bars_held >= max_bars:
            return True, "max_hold_bars"

        if bool(position.metadata.get("session_end_imminent")):
            return True, "end_of_session"

        if bool(position.metadata.get("high_impact_news_imminent")):
            return True, "pre_news"

        if config.force_end_of_day:
            opened = position.opened_at.astimezone(UTC)
            if opened.date() != current_time.astimezone(UTC).date():
                return True, "end_of_day"

        return False, ""

    def calculate_rr_ratio(
        self,
        entry: float,
        stop_loss: float,
        take_profit: float,
        side: OrderSide,
    ) -> float:
        """Calculate reward-risk ratio."""

        if side == OrderSide.BUY:
            reward = take_profit - entry
            risk = entry - stop_loss
        else:
            reward = entry - take_profit
            risk = stop_loss - entry
        if risk <= 0:
            return 0.0
        return max(reward / risk, 0.0)

    @staticmethod
    def _sl_from_support_resistance(side: OrderSide, entry: float, levels: list[float], pip_size: float) -> float:
        if side == OrderSide.BUY:
            supports = [value for value in levels if value < entry]
            return (max(supports) if supports else (entry - 10 * pip_size)) - pip_size
        resistances = [value for value in levels if value > entry]
        return (min(resistances) if resistances else (entry + 10 * pip_size)) + pip_size

    @staticmethod
    def _tp_from_support_resistance(side: OrderSide, entry: float, levels: list[float], atr: float) -> float:
        if side == OrderSide.BUY:
            targets = [value for value in levels if value > entry]
            return min(targets) if targets else (entry + atr * 2.0)
        targets = [value for value in levels if value < entry]
        return max(targets) if targets else (entry - atr * 2.0)
