from __future__ import annotations

import pytest

from data.asset_types import AssetClass
from data.models import AssetInfo
from risk.position_sizer import PositionSizer
from risk.risk_models import OrderSide, PositionSizingMethod


def _asset_info() -> AssetInfo:
    return AssetInfo(
        symbol="EURUSD",
        broker="mock_dev",
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


def test_percent_risk_formula_matches_expected_lot_size() -> None:
    sizer = PositionSizer()
    size = sizer.calculate(
        method=PositionSizingMethod.PERCENT_RISK,
        symbol="EURUSD",
        asset_class=AssetClass.FOREX,
        side=OrderSide.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        equity=10000.0,
        asset_info=_asset_info(),
        risk_pct=0.01,
    )
    assert size.units == pytest.approx(0.2, rel=1e-6)


def test_atr_based_sets_expected_size() -> None:
    sizer = PositionSizer()
    size = sizer.calculate(
        method=PositionSizingMethod.ATR_BASED,
        symbol="EURUSD",
        asset_class=AssetClass.FOREX,
        side=OrderSide.BUY,
        entry_price=1.1000,
        stop_loss=1.1000,
        equity=10000.0,
        asset_info=_asset_info(),
        atr=0.0010,
        risk_pct=0.01,
        atr_multiplier=2.0,
    )
    assert size.units == pytest.approx(0.5, rel=1e-6)


def test_kelly_fractional_positive_and_negative_expectancy() -> None:
    sizer = PositionSizer()
    positive = sizer.calculate(
        method=PositionSizingMethod.KELLY_FRACTIONAL,
        symbol="EURUSD",
        asset_class=AssetClass.FOREX,
        side=OrderSide.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        equity=10000.0,
        asset_info=_asset_info(),
        win_rate=0.6,
        avg_win_loss_ratio=1.5,
        kelly_fraction=0.25,
    )
    assert positive.units > 0

    negative = sizer.calculate(
        method=PositionSizingMethod.KELLY_FRACTIONAL,
        symbol="EURUSD",
        asset_class=AssetClass.FOREX,
        side=OrderSide.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        equity=10000.0,
        asset_info=_asset_info(),
        win_rate=0.3,
        avg_win_loss_ratio=1.0,
        kelly_fraction=0.25,
    )
    assert negative.units == 0.0


def test_size_gets_capped_by_max_position_pct() -> None:
    sizer = PositionSizer()
    size = sizer.calculate(
        method=PositionSizingMethod.FIXED_UNITS,
        symbol="EURUSD",
        asset_class=AssetClass.FOREX,
        side=OrderSide.BUY,
        entry_price=1.1000,
        stop_loss=1.0900,
        equity=10000.0,
        asset_info=_asset_info(),
        units=10.0,
        max_position_pct=0.1,
    )
    assert size.was_capped is True
    assert size.units < 10.0


def test_fixed_amount_for_btc_like_price() -> None:
    info = _asset_info().model_copy(update={"contract_size": 1.0, "pip_size": 0.01})
    sizer = PositionSizer()
    size = sizer.calculate(
        method=PositionSizingMethod.FIXED_AMOUNT,
        symbol="BTCUSD",
        asset_class=AssetClass.CRYPTO,
        side=OrderSide.BUY,
        entry_price=50000.0,
        stop_loss=49000.0,
        equity=10000.0,
        asset_info=info,
        amount=100.0,
    )
    assert size.units == pytest.approx(0.002, rel=1e-6)
