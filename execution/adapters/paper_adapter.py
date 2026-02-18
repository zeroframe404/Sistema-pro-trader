"""Paper-trading adapter implementing BaseBrokerAdapter contract."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from structlog.stdlib import BoundLogger

from core.config_models import RiskConfig
from core.event_bus import EventBus
from core.events import OrderFillEvent
from data.asset_types import AssetClass
from data.models import Tick
from execution.adapters.base_broker_adapter import BaseBrokerAdapter
from execution.fill_simulator import FillSimulator, FillSimulatorConfig
from execution.order_models import Account, Fill, Order, OrderStatus, Position, PositionStatus
from risk.risk_models import OrderSide, OrderType
from risk.slippage_model import SlippageModel


class PaperAdapter(BaseBrokerAdapter):
    """In-memory paper trading broker adapter."""

    broker = "paper"
    is_paper = True

    def __init__(
        self,
        initial_balance: float,
        fill_simulator: FillSimulator,
        slippage_model: SlippageModel,
        event_bus: EventBus,
        logger: BoundLogger,
        run_id: str,
        risk_config: RiskConfig,
    ) -> None:
        self._fill_simulator = fill_simulator
        self._slippage_model = slippage_model
        self._event_bus = event_bus
        self._logger = logger.bind(module="execution.paper_adapter")
        self._run_id = run_id
        self._config = FillSimulatorConfig(
            fill_mode=risk_config.paper.fill_mode,
            partial_fill_probability=risk_config.paper.partial_fill_probability,
            slippage=risk_config.slippage,
            commissions=risk_config.commissions,
        )
        self._connected = True

        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._fill_callbacks: list[Callable[[Fill], Awaitable[None]]] = []
        self._latest_tick: dict[str, Tick] = {}
        self._lock = asyncio.Lock()
        self._account = Account(
            account_id=f"paper-{run_id}",
            broker=self.broker,
            balance=initial_balance,
            currency=risk_config.paper.currency,
            is_paper=True,
            leverage=risk_config.paper.leverage,
            margin_used=0.0,
            unrealized_pnl=0.0,
        )

    async def get_account(self) -> Account:
        return self._account

    async def get_open_positions(self) -> list[Position]:
        return [item for item in self._positions.values() if item.status != PositionStatus.CLOSED]

    async def get_order_status(self, broker_order_id: str) -> Order:
        order = self._orders.get(broker_order_id)
        if order is None:
            raise KeyError(f"Order not found: {broker_order_id}")
        return order

    async def submit_order(self, order: Order) -> str:
        async with self._lock:
            broker_order_id = str(uuid4())
            submitted = order.model_copy(
                update={
                    "broker_order_id": broker_order_id,
                    "status": OrderStatus.SUBMITTED,
                    "submitted_at": datetime.now(UTC),
                    "is_paper": True,
                }
            )
            self._orders[broker_order_id] = submitted

            tick = self._latest_tick.get(order.symbol)
            if tick is None:
                base = order.price if order.price is not None else 1.0
                tick = Tick(
                    symbol=order.symbol,
                    broker=order.broker,
                    timestamp=datetime.now(UTC),
                    bid=base,
                    ask=base,
                    last=base,
                    volume=0.0,
                    spread=0.0,
                    source="paper_adapter",
                )
                self._latest_tick[order.symbol] = tick

            fill = self._fill_simulator.simulate_fill(submitted, tick, [], self._config)
            if fill is not None:
                await self._on_fill(fill, broker_order_id)

            return broker_order_id

    async def cancel_order(self, broker_order_id: str) -> bool:
        order = self._orders.get(broker_order_id)
        if order is None:
            return False
        if order.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return False
        self._orders[broker_order_id] = order.model_copy(
            update={"status": OrderStatus.CANCELLED, "cancelled_at": datetime.now(UTC)}
        )
        return True

    async def modify_order(self, broker_order_id: str, new_sl: float | None, new_tp: float | None) -> bool:
        order = self._orders.get(broker_order_id)
        if order is None:
            return False
        self._orders[broker_order_id] = order.model_copy(update={"stop_loss": new_sl, "take_profit": new_tp})
        return True

    async def close_position(self, position: Position, partial_pct: float = 1.0) -> str:
        close_qty = max(min(partial_pct, 1.0), 0.0) * position.quantity
        close_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
        close_order = Order(
            client_order_id=str(uuid4())[:24],
            signal_id=position.signal_id,
            risk_check_id="close_position",
            symbol=position.symbol,
            broker=position.broker,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=max(close_qty, 0.0000001),
            price=position.current_price,
            stop_loss=None,
            take_profit=None,
            trailing_stop=None,
            time_in_force="IOC",
            status=OrderStatus.PENDING,
            is_paper=True,
            metadata={"close_position_id": position.position_id, **position.metadata},
        )
        return await self.submit_order(close_order)

    async def subscribe_fills(self, callback: Callable[[Fill], Awaitable[None]]) -> None:
        self._fill_callbacks.append(callback)

    async def ping(self) -> float:
        return 1.0

    def is_connected(self) -> bool:
        return self._connected

    async def list_orders(self) -> list[Order]:
        return list(self._orders.values())

    async def process_tick(self, tick: Tick) -> None:
        """Update positions and trigger TP/SL checks on incoming tick."""

        self._latest_tick[tick.symbol] = tick
        open_positions = [item for item in self._positions.values() if item.status == PositionStatus.OPEN and item.symbol == tick.symbol]
        for position in open_positions:
            mark = tick.bid if position.side == OrderSide.BUY else tick.ask
            contract_size = float(position.metadata.get("contract_size", 1.0))
            pnl_per_unit = (mark - position.entry_price) if position.side == OrderSide.BUY else (position.entry_price - mark)
            position.current_price = mark
            position.unrealized_pnl = pnl_per_unit * position.quantity * contract_size - position.commission_total

            if self._fill_simulator.should_trigger_sl(position, tick):
                await self.close_position(position, partial_pct=1.0)
                continue
            if self._fill_simulator.should_trigger_tp(position, tick):
                await self.close_position(position, partial_pct=1.0)

        self._update_account_unrealized()

    async def _on_fill(self, fill: Fill, broker_order_id: str) -> None:
        order = self._orders[broker_order_id]
        total_qty = order.filled_quantity + fill.quantity
        weighted_price = (
            ((order.average_fill_price or 0.0) * order.filled_quantity + fill.price * fill.quantity) / max(total_qty, 1e-12)
        )
        status = OrderStatus.PARTIALLY_FILLED if fill.is_partial and total_qty < order.quantity else OrderStatus.FILLED
        updated_order = order.model_copy(
            update={
                "filled_quantity": total_qty,
                "average_fill_price": weighted_price,
                "filled_at": fill.timestamp,
                "status": status,
                "commission": order.commission + fill.commission,
            }
        )
        self._orders[broker_order_id] = updated_order

        close_position_id = updated_order.metadata.get("close_position_id")
        if isinstance(close_position_id, str):
            await self._apply_close_fill(close_position_id, fill)
        else:
            await self._apply_open_fill(updated_order, fill)

        await self._event_bus.publish(
            OrderFillEvent(
                source="execution.paper_adapter",
                run_id=self._run_id,
                order_id=updated_order.order_id,
                client_order_id=updated_order.client_order_id,
                risk_check_id=updated_order.risk_check_id,
                symbol=updated_order.symbol,
                broker=updated_order.broker,
                direction=updated_order.side.value,
                order_type=updated_order.order_type.value,
                quantity=updated_order.quantity,
                price=updated_order.price,
                stop_loss=updated_order.stop_loss,
                take_profit=updated_order.take_profit,
                status=updated_order.status.value,
                is_paper=True,
                metadata=updated_order.metadata,
                fill_price=fill.price,
                fill_quantity=fill.quantity,
            )
        )

        for callback in self._fill_callbacks:
            await callback(fill)

    async def _apply_open_fill(self, order: Order, fill: Fill) -> None:
        position = Position(
            symbol=order.symbol,
            broker=order.broker,
            side=order.side,
            quantity=fill.quantity,
            entry_price=fill.price,
            current_price=fill.price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            trailing_stop_price=None,
            status=PositionStatus.OPEN,
            unrealized_pnl=0.0,
            realized_pnl=None,
            commission_total=fill.commission,
            signal_id=order.signal_id,
            strategy_id=str(order.metadata.get("strategy_id", "signal_ensemble")),
            asset_class=AssetClass(str(order.metadata.get("asset_class", "unknown"))),
            is_paper=True,
            metadata=order.metadata,
        )
        self._positions[position.position_id] = position
        self._account.balance -= fill.commission
        self._update_account_unrealized()

    async def _apply_close_fill(self, position_id: str, fill: Fill) -> None:
        position = self._positions.get(position_id)
        if position is None:
            return
        close_qty = min(fill.quantity, position.quantity)
        contract_size = float(position.metadata.get("contract_size", 1.0))
        pnl_per_unit = (fill.price - position.entry_price) if position.side == OrderSide.BUY else (position.entry_price - fill.price)
        realized = pnl_per_unit * close_qty * contract_size - fill.commission
        position.quantity -= close_qty
        position.commission_total += fill.commission
        if position.quantity <= 1e-12:
            position.quantity = 0.0
            position.status = PositionStatus.CLOSED
            position.closed_at = fill.timestamp
            position.close_price = fill.price
            position.realized_pnl = (position.realized_pnl or 0.0) + realized
        else:
            position.realized_pnl = (position.realized_pnl or 0.0) + realized
        self._account.balance += realized
        self._update_account_unrealized()

    def _update_account_unrealized(self) -> None:
        total_unrealized = sum(
            item.unrealized_pnl for item in self._positions.values() if item.status == PositionStatus.OPEN
        )
        self._account.unrealized_pnl = total_unrealized
        self._account.updated_at = datetime.now(UTC)
        self._account = self._account.model_copy(update={})
