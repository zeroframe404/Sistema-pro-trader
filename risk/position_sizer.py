"""Position sizing strategies used by risk manager."""

from __future__ import annotations

from typing import Any

from data.asset_types import AssetClass
from data.models import AssetInfo
from risk.risk_models import OrderSide, PositionSize, PositionSizingMethod


class PositionSizer:
    """Calculate a conservative position size from risk parameters."""

    def calculate(
        self,
        method: PositionSizingMethod,
        symbol: str,
        asset_class: AssetClass,
        side: OrderSide,
        entry_price: float,
        stop_loss: float,
        equity: float,
        asset_info: AssetInfo,
        atr: float | None = None,
        win_rate: float | None = None,
        avg_win_loss_ratio: float | None = None,
        **params: Any,
    ) -> PositionSize:
        """Route sizing request and always return a safe result."""

        _ = (symbol, asset_class, side)
        try:
            if method == PositionSizingMethod.FIXED_UNITS:
                size = self._fixed_units(
                    units=float(params.get("units", 0.0)),
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    equity=equity,
                    asset_info=asset_info,
                )
            elif method == PositionSizingMethod.FIXED_AMOUNT:
                size = self._fixed_amount(
                    amount=float(params.get("amount", 0.0)),
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    equity=equity,
                    asset_info=asset_info,
                )
            elif method in {PositionSizingMethod.PERCENT_EQUITY, PositionSizingMethod.PERCENT_RISK}:
                risk_pct = self._normalize_pct(float(params.get("risk_pct", params.get("pct", 0.0))))
                size = self._percent_equity(
                    equity=equity,
                    risk_pct=risk_pct,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    asset_info=asset_info,
                )
            elif method == PositionSizingMethod.ATR_BASED:
                risk_pct = self._normalize_pct(float(params.get("risk_pct", params.get("pct", 0.0))))
                size = self._atr_based(
                    equity=equity,
                    risk_pct=risk_pct,
                    entry_price=entry_price,
                    atr=float(atr if atr is not None else params.get("atr", 0.0)),
                    atr_multiplier=float(params.get("atr_multiplier", 2.0)),
                    stop_side=side,
                    asset_info=asset_info,
                )
            elif method == PositionSizingMethod.KELLY_FRACTIONAL:
                size = self._kelly_fractional(
                    equity=equity,
                    win_rate=float(win_rate if win_rate is not None else params.get("win_rate", 0.0)),
                    avg_win_loss_ratio=float(
                        avg_win_loss_ratio if avg_win_loss_ratio is not None else params.get("avg_win_loss_ratio", 0.0)
                    ),
                    kelly_fraction=float(params.get("kelly_fraction", 0.25)),
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    asset_info=asset_info,
                )
            else:
                size = self._zero_size(method)
        except Exception:  # noqa: BLE001
            size = self._zero_size(method)
            size.was_capped = True
            size.cap_reason = "invalid_inputs_fallback"

        max_position_pct_raw = params.get("max_position_pct")
        max_position_pct = (
            self._normalize_pct(float(max_position_pct_raw))
            if max_position_pct_raw is not None
            else None
        )
        return self._apply_caps(
            size=size,
            max_position_pct=max_position_pct,
            max_units=float(params["max_units"]) if params.get("max_units") is not None else None,
            equity=equity,
            max_risk_per_trade_pct=self._normalize_pct(float(params.get("max_risk_per_trade_pct", 1.0))),
        )

    def _fixed_units(
        self,
        *,
        units: float,
        entry_price: float,
        stop_loss: float,
        equity: float,
        asset_info: AssetInfo,
    ) -> PositionSize:
        units = max(units, 0.0)
        notional = units * entry_price * self._contract_size(asset_info)
        risk_amount = units * abs(entry_price - stop_loss) * self._contract_size(asset_info)
        risk_percent = (risk_amount / equity) if equity > 0 else 0.0
        return PositionSize(
            method=PositionSizingMethod.FIXED_UNITS,
            units=units,
            notional_value=notional,
            risk_amount=risk_amount,
            risk_percent=risk_percent,
            max_allowed_units=max(units, 0.0),
        )

    def _fixed_amount(
        self,
        *,
        amount: float,
        entry_price: float,
        stop_loss: float,
        equity: float,
        asset_info: AssetInfo,
    ) -> PositionSize:
        contract = self._contract_size(asset_info)
        units = max(amount, 0.0) / max(entry_price * contract, 1e-12)
        return self._fixed_units(
            units=units,
            entry_price=entry_price,
            stop_loss=stop_loss,
            equity=equity,
            asset_info=asset_info,
        ).model_copy(update={"method": PositionSizingMethod.FIXED_AMOUNT})

    def _percent_equity(
        self,
        *,
        equity: float,
        risk_pct: float,
        entry_price: float,
        stop_loss: float,
        asset_info: AssetInfo,
    ) -> PositionSize:
        risk_pct = max(risk_pct, 0.0)
        risk_usd = max(equity, 0.0) * risk_pct
        sl_distance = abs(entry_price - stop_loss)
        contract = self._contract_size(asset_info)
        denom = max(sl_distance * contract, 1e-12)
        units = risk_usd / denom
        notional = units * entry_price * contract
        return PositionSize(
            method=PositionSizingMethod.PERCENT_EQUITY,
            units=max(units, 0.0),
            notional_value=max(notional, 0.0),
            risk_amount=max(risk_usd, 0.0),
            risk_percent=(risk_usd / equity) if equity > 0 else 0.0,
            max_allowed_units=max(units, 0.0),
        )

    def _atr_based(
        self,
        *,
        equity: float,
        risk_pct: float,
        entry_price: float,
        atr: float,
        atr_multiplier: float,
        stop_side: OrderSide,
        asset_info: AssetInfo,
    ) -> PositionSize:
        atr = max(atr, 0.0)
        sl_distance = atr * max(atr_multiplier, 0.1)
        if stop_side == OrderSide.BUY:
            stop_loss = entry_price - sl_distance
        else:
            stop_loss = entry_price + sl_distance
        return self._percent_equity(
            equity=equity,
            risk_pct=risk_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
            asset_info=asset_info,
        ).model_copy(update={"method": PositionSizingMethod.ATR_BASED})

    def _kelly_fractional(
        self,
        *,
        equity: float,
        win_rate: float,
        avg_win_loss_ratio: float,
        kelly_fraction: float,
        entry_price: float,
        stop_loss: float,
        asset_info: AssetInfo,
    ) -> PositionSize:
        warnings: list[str] = []
        ratio = max(avg_win_loss_ratio, 1e-12)
        p = min(max(win_rate, 0.0), 1.0)
        full_kelly = (p * (ratio + 1.0) - 1.0) / ratio
        if full_kelly <= 0:
            return self._zero_size(PositionSizingMethod.KELLY_FRACTIONAL).model_copy(
                update={"warnings": ["negative_expectancy_no_bet"]}
            )
        if kelly_fraction > 0.5:
            warnings.append("kelly_fraction_aggressive")
        effective = max(0.0, min(full_kelly * max(kelly_fraction, 0.0), 1.0))
        sized = self._percent_equity(
            equity=equity,
            risk_pct=effective,
            entry_price=entry_price,
            stop_loss=stop_loss,
            asset_info=asset_info,
        ).model_copy(update={"method": PositionSizingMethod.KELLY_FRACTIONAL})
        return sized.model_copy(update={"warnings": warnings})

    def _apply_caps(
        self,
        *,
        size: PositionSize,
        max_position_pct: float | None,
        max_units: float | None,
        equity: float,
        max_risk_per_trade_pct: float,
    ) -> PositionSize:
        units = size.units
        was_capped = size.was_capped
        cap_reason = size.cap_reason

        if max_position_pct is not None and max_position_pct > 0 and equity > 0 and size.notional_value > (equity * max_position_pct):
            ratio = (equity * max_position_pct) / max(size.notional_value, 1e-12)
            units *= ratio
            was_capped = True
            cap_reason = cap_reason or "max_position_pct"

        if max_units is not None and units > max_units:
            units = max_units
            was_capped = True
            cap_reason = cap_reason or "max_units"

        if equity > 0 and size.risk_amount > (equity * max_risk_per_trade_pct):
            ratio = (equity * max_risk_per_trade_pct) / max(size.risk_amount, 1e-12)
            units *= ratio
            was_capped = True
            cap_reason = cap_reason or "max_risk_per_trade_pct"

        if units == size.units:
            return size

        scale = units / max(size.units, 1e-12)
        return size.model_copy(
            update={
                "units": max(units, 0.0),
                "notional_value": max(size.notional_value * scale, 0.0),
                "risk_amount": max(size.risk_amount * scale, 0.0),
                "risk_percent": max(size.risk_percent * scale, 0.0),
                "max_allowed_units": max(units, 0.0),
                "was_capped": was_capped,
                "cap_reason": cap_reason,
            }
        )

    @staticmethod
    def _contract_size(asset_info: AssetInfo) -> float:
        return max(float(asset_info.contract_size), 1e-12)

    @staticmethod
    def _normalize_pct(raw_value: float) -> float:
        return (raw_value / 100.0) if raw_value > 1.0 else max(raw_value, 0.0)

    @staticmethod
    def _zero_size(method: PositionSizingMethod) -> PositionSize:
        return PositionSize(
            method=method,
            units=0.0,
            notional_value=0.0,
            risk_amount=0.0,
            risk_percent=0.0,
            max_allowed_units=0.0,
        )
