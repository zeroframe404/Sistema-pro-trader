"""Portfolio exposure tracking and anti-concentration checks."""

from __future__ import annotations

from collections import defaultdict

from core.config_models import ExposureLimitsConfig
from data.asset_types import AssetClass
from execution.order_models import Position

CORRELATION_GROUPS: dict[str, str] = {
    "EURUSD": "usd_fx",
    "GBPUSD": "usd_fx",
    "AUDUSD": "usd_fx",
    "NZDUSD": "usd_fx",
    "USDCAD": "usd_fx",
    "USDCHF": "usd_fx",
    "USDJPY": "usd_fx",
    "BTCUSD": "usd_quote",
    "ETHUSD": "usd_quote",
    "SPY": "us_equity",
    "QQQ": "us_equity",
}


class ExposureTracker:
    """Track and validate current portfolio exposure."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def add_position(self, position: Position) -> None:
        """Register an open position."""

        self._positions[position.position_id] = position

    def remove_position(self, position_id: str) -> None:
        """Remove a closed position."""

        self._positions.pop(position_id, None)

    def update_price(self, symbol: str, price: float) -> None:
        """Update current mark price for all matching positions."""

        for position in self._positions.values():
            if position.symbol == symbol:
                position.current_price = price

    def get_exposure_pct(self, symbol: str, equity: float) -> float:
        """Return symbol notional exposure as percent of equity."""

        notional = sum(self._position_notional(item) for item in self._positions.values() if item.symbol == symbol)
        return self._pct(notional, equity)

    def get_exposure_by_asset_class(self, equity: float) -> dict[str, float]:
        """Return exposure percentages by asset class."""

        grouped: dict[str, float] = defaultdict(float)
        for position in self._positions.values():
            grouped[position.asset_class.value] += self._position_notional(position)
        return {key: self._pct(value, equity) for key, value in grouped.items()}

    def get_correlated_exposure(self, symbol: str, equity: float) -> float:
        """Return exposure percentage including correlated symbols."""

        group = CORRELATION_GROUPS.get(symbol, symbol)
        notional = 0.0
        for position in self._positions.values():
            current_group = CORRELATION_GROUPS.get(position.symbol, position.symbol)
            if current_group == group:
                notional += self._position_notional(position)
        return self._pct(notional, equity)

    def would_exceed_limits(
        self,
        symbol: str,
        asset_class: AssetClass,
        new_exposure_notional: float,
        equity: float,
        limits: ExposureLimitsConfig,
    ) -> list[str]:
        """Simulate adding notional and return violated limit names."""

        violations: list[str] = []

        current_symbol_notional = sum(
            self._position_notional(item) for item in self._positions.values() if item.symbol == symbol
        )
        next_symbol_pct = self._pct(current_symbol_notional + new_exposure_notional, equity)
        if next_symbol_pct > limits.max_exposure_per_symbol_pct:
            violations.append("max_exposure_per_symbol_pct")

        by_asset: dict[AssetClass, float] = defaultdict(float)
        for position in self._positions.values():
            by_asset[position.asset_class] += self._position_notional(position)
        by_asset[asset_class] += new_exposure_notional
        next_asset_pct = self._pct(by_asset[asset_class], equity)
        if next_asset_pct > limits.max_exposure_per_asset_class_pct:
            violations.append("max_exposure_per_asset_class_pct")

        current_corr_pct = self.get_correlated_exposure(symbol, equity)
        new_corr_pct = current_corr_pct + self._pct(new_exposure_notional, equity)
        if new_corr_pct > limits.max_correlated_exposure_pct:
            violations.append("max_correlated_exposure_pct")

        return violations

    def get_total_exposure_pct(self, equity: float) -> float:
        """Return total notional exposure as percent of equity."""

        notional = sum(self._position_notional(item) for item in self._positions.values())
        return self._pct(notional, equity)

    def list_positions(self) -> list[Position]:
        """Return tracked positions."""

        return list(self._positions.values())

    @staticmethod
    def _position_notional(position: Position) -> float:
        contract_size = float(position.metadata.get("contract_size", 1.0))
        return abs(position.quantity * position.current_price * contract_size)

    @staticmethod
    def _pct(value: float, equity: float) -> float:
        if equity <= 0:
            return 0.0
        return (value / equity) * 100.0
