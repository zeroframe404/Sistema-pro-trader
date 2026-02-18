from __future__ import annotations

from core.config_models import ExposureLimitsConfig
from data.asset_types import AssetClass
from execution.order_models import Position
from risk.exposure_tracker import ExposureTracker
from risk.risk_models import OrderSide


def _position(symbol: str, qty: float, price: float, asset_class: AssetClass = AssetClass.FOREX) -> Position:
    return Position(
        symbol=symbol,
        broker="paper",
        side=OrderSide.BUY,
        quantity=qty,
        entry_price=price,
        current_price=price,
        stop_loss=price - 0.001,
        take_profit=price + 0.002,
        trailing_stop_price=None,
        unrealized_pnl=0.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id=f"sig-{symbol}",
        strategy_id="s",
        asset_class=asset_class,
        metadata={"contract_size": 100000.0},
    )


def test_add_and_remove_position_updates_exposure() -> None:
    tracker = ExposureTracker()
    p = _position("EURUSD", 0.2, 1.1)
    tracker.add_position(p)
    assert tracker.get_exposure_pct("EURUSD", 10000.0) > 0.0
    tracker.remove_position(p.position_id)
    assert tracker.get_exposure_pct("EURUSD", 10000.0) == 0.0


def test_correlated_exposure_includes_usd_block() -> None:
    tracker = ExposureTracker()
    tracker.add_position(_position("EURUSD", 0.2, 1.1))
    tracker.add_position(_position("GBPUSD", 0.2, 1.25))
    pct = tracker.get_correlated_exposure("AUDUSD", 10000.0)
    assert pct > 0.0


def test_would_exceed_limits_for_symbol_and_correlated() -> None:
    tracker = ExposureTracker()
    tracker.add_position(_position("EURUSD", 0.2, 1.1))
    limits = ExposureLimitsConfig(
        max_exposure_per_symbol_pct=10.0,
        max_exposure_per_asset_class_pct=30.0,
        max_correlated_exposure_pct=20.0,
    )
    violations = tracker.would_exceed_limits(
        symbol="GBPUSD",
        asset_class=AssetClass.FOREX,
        new_exposure_notional=10000.0,
        equity=10000.0,
        limits=limits,
    )
    assert "max_correlated_exposure_pct" in violations
