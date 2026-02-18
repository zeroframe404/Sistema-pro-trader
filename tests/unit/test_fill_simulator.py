from __future__ import annotations

from datetime import UTC, datetime

from core.config_models import CommissionsConfig, SlippageConfig, SlippageMethod
from data.models import Tick
from execution.fill_simulator import FillSimulator, FillSimulatorConfig
from execution.order_models import Order, Position
from risk.risk_models import OrderSide, OrderType
from risk.slippage_model import SlippageModel


def _order(order_type: OrderType, side: OrderSide, price: float | None = None) -> Order:
    return Order(
        client_order_id="cid",
        signal_id="sig",
        risk_check_id="rc",
        symbol="EURUSD",
        broker="paper",
        side=side,
        order_type=order_type,
        quantity=1.0,
        price=price,
        stop_price=price,
        stop_loss=1.095,
        take_profit=1.105,
        trailing_stop=None,
        time_in_force="GTC",
        is_paper=True,
        metadata={"asset_class": "forex", "contract_size": 100000.0, "pip_size": 0.0001},
    )


def _tick() -> Tick:
    return Tick(
        symbol="EURUSD",
        broker="paper",
        timestamp=datetime.now(UTC),
        bid=1.1000,
        ask=1.1002,
        last=1.1001,
        volume=1.0,
        spread=0.0002,
        source="test",
    )


def test_market_buy_and_sell_fill_with_spread_based_slippage() -> None:
    simulator = FillSimulator(SlippageModel())
    cfg = FillSimulatorConfig(
        fill_mode="instant",
        partial_fill_probability=0.0,
        slippage=SlippageConfig(method=SlippageMethod.SPREAD_BASED),
        commissions=CommissionsConfig(),
    )
    buy_fill = simulator.simulate_fill(_order(OrderType.MARKET, OrderSide.BUY), _tick(), [], cfg)
    sell_fill = simulator.simulate_fill(_order(OrderType.MARKET, OrderSide.SELL), _tick(), [], cfg)
    assert buy_fill is not None
    assert sell_fill is not None
    assert buy_fill.price > _tick().ask
    assert sell_fill.price < _tick().bid


def test_limit_buy_fill_conditions() -> None:
    simulator = FillSimulator(SlippageModel())
    cfg = FillSimulatorConfig(fill_mode="instant", partial_fill_probability=0.0)
    fill_ok = simulator.simulate_fill(_order(OrderType.LIMIT, OrderSide.BUY, price=1.1003), _tick(), [], cfg)
    fill_none = simulator.simulate_fill(_order(OrderType.LIMIT, OrderSide.BUY, price=1.0999), _tick(), [], cfg)
    assert fill_ok is not None
    assert fill_none is None


def test_should_trigger_sl_and_tp() -> None:
    simulator = FillSimulator(SlippageModel())
    tick = _tick()
    position = Position(
        symbol="EURUSD",
        broker="paper",
        side=OrderSide.BUY,
        quantity=1.0,
        entry_price=1.1000,
        current_price=1.1000,
        stop_loss=1.1001,
        take_profit=1.0999,
        trailing_stop_price=None,
        unrealized_pnl=0.0,
        realized_pnl=None,
        commission_total=0.0,
        signal_id="sig",
        strategy_id="s",
    )
    assert simulator.should_trigger_sl(position, tick) is True
    assert simulator.should_trigger_tp(position, tick) is True
