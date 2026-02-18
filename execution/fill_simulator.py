"""Fill simulation for paper trading and backtest-like execution."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from core.config_models import CommissionsConfig, SlippageConfig
from data.asset_types import AssetClass
from data.models import AssetInfo, OHLCVBar, Tick
from execution.order_models import Fill, Order, Position
from risk.risk_models import OrderSide, OrderType
from risk.slippage_model import SlippageModel


class FillSimulatorConfig(BaseModel):
    """Runtime settings for simulated fills."""

    fill_mode: str = "realistic"
    partial_fill_probability: float = Field(default=0.05, ge=0.0, le=1.0)
    slippage: SlippageConfig = Field(default_factory=SlippageConfig)
    commissions: CommissionsConfig = Field(default_factory=CommissionsConfig)


class FillSimulator:
    """Simulate fills based on current tick and order constraints."""

    def __init__(self, slippage_model: SlippageModel) -> None:
        self._slippage_model = slippage_model

    def simulate_fill(
        self,
        order: Order,
        current_tick: Tick,
        current_bars: list[OHLCVBar],
        config: FillSimulatorConfig,
    ) -> Fill | None:
        """Return Fill when order would execute, otherwise None."""

        _ = current_bars
        if order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and (order.price is None or current_tick.ask > order.price):
                return None
            if order.side == OrderSide.SELL and (order.price is None or current_tick.bid < order.price):
                return None
            fill_price = float(order.price if order.price is not None else current_tick.last or current_tick.ask)
        elif order.order_type in {OrderType.STOP, OrderType.STOP_LIMIT}:
            if order.stop_price is None:
                return None
            if order.side == OrderSide.BUY and current_tick.ask < order.stop_price:
                return None
            if order.side == OrderSide.SELL and current_tick.bid > order.stop_price:
                return None
            fill_price = self._slippage_model.apply_slippage(
                order_price=order.stop_price,
                side=order.side,
                order_type=OrderType.MARKET,
                current_tick=current_tick,
                atr=None,
                asset_info=self._asset_info(order),
                config=config.slippage,
            )
        else:
            fill_price = self._slippage_model.apply_slippage(
                order_price=order.price if order.price is not None else (current_tick.last or current_tick.ask),
                side=order.side,
                order_type=order.order_type,
                current_tick=current_tick,
                atr=None,
                asset_info=self._asset_info(order),
                config=config.slippage,
            )

        fill_qty = order.quantity
        is_partial = False
        if config.fill_mode == "realistic" and random.random() < config.partial_fill_probability:
            fill_qty = max(order.quantity * random.uniform(0.25, 0.95), 0.0000001)
            is_partial = True

        commission = self._slippage_model.calculate_commission(
            fill_price=fill_price,
            units=fill_qty,
            asset_info=self._asset_info(order),
            config=config.commissions,
        )
        return Fill(
            order_id=order.order_id,
            broker_fill_id=None,
            symbol=order.symbol,
            broker=order.broker,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            commission=commission,
            timestamp=datetime.now(UTC),
            is_partial=is_partial,
            is_paper=order.is_paper,
        )

    def simulate_partial_fill(self, order: Order, fill_pct: float, current_tick: Tick) -> Fill:
        """Force a partial fill with given percentage."""

        qty = max(min(fill_pct, 1.0), 0.0) * order.quantity
        fill_price = current_tick.ask if order.side == OrderSide.BUY else current_tick.bid
        return Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            broker=order.broker,
            side=order.side,
            quantity=max(qty, 0.0000001),
            price=fill_price,
            commission=0.0,
            timestamp=datetime.now(UTC),
            is_partial=True,
            is_paper=order.is_paper,
        )

    def should_trigger_sl(self, position: Position, current_tick: Tick) -> bool:
        """Return true if stop-loss should trigger."""

        if position.stop_loss is None:
            return False
        if position.side == OrderSide.BUY:
            return current_tick.bid <= position.stop_loss
        return current_tick.ask >= position.stop_loss

    def should_trigger_tp(self, position: Position, current_tick: Tick) -> bool:
        """Return true if take-profit should trigger."""

        if position.take_profit is None:
            return False
        if position.side == OrderSide.BUY:
            return current_tick.bid >= position.take_profit
        return current_tick.ask <= position.take_profit

    @staticmethod
    def _asset_info(order: Order) -> AssetInfo:
        contract_size = float(order.metadata.get("contract_size", 1.0))
        pip_size = float(order.metadata.get("pip_size", 0.0001))
        asset_class_raw = order.metadata.get("asset_class", "unknown")
        asset_class = AssetClass(asset_class_raw) if isinstance(asset_class_raw, str) else AssetClass.UNKNOWN
        return AssetInfo(
            symbol=order.symbol,
            broker=order.broker,
            name=order.symbol,
            asset_class=asset_class,
            currency="USD",
            contract_size=contract_size,
            pip_size=pip_size,
            min_volume=0.0,
            max_volume=1_000_000.0,
            volume_step=0.01,
            digits=5,
            trading_hours={},
            available_timeframes=[],
            supported_order_types=["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
        )
