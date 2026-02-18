"""Slippage and commission model for paper/live simulations."""

from __future__ import annotations

from core.config_models import CommissionRuleConfig, CommissionsConfig, SlippageConfig
from data.asset_types import AssetClass
from data.models import AssetInfo, Tick
from risk.risk_models import OrderSide, OrderType


class SlippageModel:
    """Apply execution slippage and commissions in a deterministic way."""

    def apply_slippage(
        self,
        order_price: float,
        side: OrderSide,
        order_type: OrderType,
        current_tick: Tick | None,
        atr: float | None,
        asset_info: AssetInfo,
        config: SlippageConfig,
    ) -> float:
        """Return slippage-adjusted fill price."""

        if order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT}:
            return order_price

        bid = current_tick.bid if current_tick is not None else order_price
        ask = current_tick.ask if current_tick is not None else order_price
        spread = (
            current_tick.spread
            if (current_tick is not None and current_tick.spread is not None)
            else max(ask - bid, float(asset_info.pip_size or 0.0001))
        )

        if config.method.value == "fixed_pips":
            slip = float(asset_info.pip_size or 0.0001) * config.fixed_pips
        elif config.method.value == "percent":
            base = ask if side == OrderSide.BUY else bid
            slip = base * config.percent
        elif config.method.value == "volatility_based":
            slip = max(float(atr or 0.0) * 0.1, float(asset_info.pip_size or 0.0001))
        else:
            slip = spread

        if side == OrderSide.BUY:
            return (ask if order_type == OrderType.MARKET else order_price) + slip
        return (bid if order_type == OrderType.MARKET else order_price) - slip

    def calculate_commission(
        self,
        fill_price: float,
        units: float,
        asset_info: AssetInfo,
        config: CommissionsConfig,
    ) -> float:
        """Calculate commission amount for one fill."""

        rule = self._select_commission_rule(asset_info.asset_class, config)
        if rule.method.value == "per_lot":
            return float(units * rule.amount_per_lot)
        if rule.method.value == "percent":
            return float(fill_price * units * max(asset_info.contract_size, 1.0) * rule.pct)
        if rule.method.value == "per_share":
            return float(units * max(asset_info.contract_size, 1.0) * rule.amount_per_share)
        if rule.method.value == "fixed":
            return float(rule.fixed_amount)
        return 0.0

    @staticmethod
    def _select_commission_rule(asset_class: AssetClass, config: CommissionsConfig) -> CommissionRuleConfig:
        if asset_class == AssetClass.FOREX:
            return config.forex
        if asset_class == AssetClass.CRYPTO:
            return config.crypto
        if asset_class in {AssetClass.STOCK, AssetClass.ETF, AssetClass.CEDEAR, AssetClass.BOND}:
            return config.stock
        if asset_class == AssetClass.BINARY_OPTION:
            return config.binary_option
        if asset_class == AssetClass.FIXED_TERM:
            return config.fixed_term
        return config.stock
