"""Base broker adapter interface for OMS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from execution.order_models import Account, Fill, Order, Position


class BaseBrokerAdapter(ABC):
    """Unified broker adapter contract used by order manager."""

    broker: str
    is_paper: bool

    @abstractmethod
    async def get_account(self) -> Account:
        """Return account snapshot."""

    @abstractmethod
    async def get_open_positions(self) -> list[Position]:
        """Return open positions."""

    @abstractmethod
    async def get_order_status(self, broker_order_id: str) -> Order:
        """Return one broker order status."""

    @abstractmethod
    async def submit_order(self, order: Order) -> str:
        """Submit order and return broker order id."""

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel broker order."""

    @abstractmethod
    async def modify_order(self, broker_order_id: str, new_sl: float | None, new_tp: float | None) -> bool:
        """Modify broker order stops."""

    @abstractmethod
    async def close_position(self, position: Position, partial_pct: float = 1.0) -> str:
        """Close position and return close order broker id."""

    @abstractmethod
    async def subscribe_fills(self, callback: Callable[[Fill], Awaitable[None]]) -> None:
        """Subscribe to fill notifications."""

    @abstractmethod
    async def ping(self) -> float:
        """Return adapter latency in milliseconds."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return connection state."""

    async def list_orders(self) -> list[Order]:
        """Optional full order list for reconciliation."""

        return []
