from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.config_models import StopConfig, TimeExitConfig, TrailingConfig, TrailingStopMethod
from data.asset_types import AssetClass
from data.models import AssetInfo
from execution.order_models import Position
from risk.risk_models import OrderSide
from risk.stop_manager import StopManager


def _asset_info() -> AssetInfo:
    return AssetInfo(
        symbol="EURUSD",
        broker="mock",
        name="EURUSD",
        asset_class=AssetClass.FOREX,
        currency="USD",
        contract_size=100000.0,
        min_volume=0.01,
        max_volume=100.0,
        volume_step=0.01,
        pip_size=0.0001,
        digits=5,
        trading_hours={},
        available_timeframes=["M1", "M5", "H1"],
        supported_order_types=["MARKET", "LIMIT", "STOP"],
    )


def test_calculate_stops_buy_and_sell_directional() -> None:
    manager = StopManager()
    config = StopConfig()
    sl_buy, tp_buy, _ = manager.calculate_stops("EURUSD", OrderSide.BUY, 1.1, 0.001, _asset_info(), config)
    sl_sell, tp_sell, _ = manager.calculate_stops("EURUSD", OrderSide.SELL, 1.1, 0.001, _asset_info(), config)
    assert sl_buy < 1.1 and tp_buy > 1.1
    assert sl_sell > 1.1 and tp_sell < 1.1


def test_atr_based_sl_distance() -> None:
    manager = StopManager()
    config = StopConfig(atr_multiplier_sl=2.0)
    sl, _, _ = manager.calculate_stops("EURUSD", OrderSide.BUY, 1.1000, 0.0010, _asset_info(), config)
    assert sl == pytest.approx(1.0980, rel=1e-6)


def test_calculate_rr_ratio_buy_sell() -> None:
    manager = StopManager()
    buy_rr = manager.calculate_rr_ratio(1.1000, 1.0950, 1.1100, OrderSide.BUY)
    sell_rr = manager.calculate_rr_ratio(1.1000, 1.1050, 1.0900, OrderSide.SELL)
    assert buy_rr == pytest.approx(2.0, rel=1e-6)
    assert sell_rr == pytest.approx(2.0, rel=1e-6)


def test_should_trail_moves_only_in_favor() -> None:
    manager = StopManager()
    pos = Position(
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=1.0,
        entry_price=1.1000,
        current_price=1.1010,
        stop_loss=1.0950,
        take_profit=1.1100,
        trailing_stop_price=None,
        unrealized_pnl=0.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id="sig",
        strategy_id="s",
        metadata={"pip_size": 0.0001},
    )
    cfg = TrailingConfig(method=TrailingStopMethod.ATR_BASED, atr_multiplier=1.0)
    moved = manager.should_trail(pos, current_price=1.1030, atr=0.001, config=cfg)
    not_moved = manager.should_trail(pos, current_price=1.0940, atr=0.001, config=cfg)
    assert moved is not None
    assert not_moved is None


def test_should_exit_by_time_when_max_bars_reached() -> None:
    manager = StopManager()
    pos = Position(
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=1.0,
        entry_price=1.1000,
        current_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        trailing_stop_price=None,
        unrealized_pnl=0.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id="sig",
        strategy_id="s",
        metadata={"timeframe": "H1", "bars_held": 48},
    )
    should_exit, reason = manager.should_exit_by_time(pos, datetime.now(UTC), TimeExitConfig())
    assert should_exit is True
    assert reason == "max_hold_bars"
