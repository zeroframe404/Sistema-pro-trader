"""Strategy selection by asset class, regime and horizon."""

from __future__ import annotations

from core.config_models import SignalsConfig, SignalStrategyConfig
from data.asset_types import AssetClass, TradingHorizon
from regime.regime_models import MarketRegime


class AssetStrategySelector:
    """Resolve active signal strategies for a context."""

    def __init__(self, config: SignalsConfig) -> None:
        self._config = config

    def select(
        self,
        *,
        asset_class: AssetClass,
        regime: MarketRegime,
        horizon_class: TradingHorizon,
    ) -> list[SignalStrategyConfig]:
        """Return enabled strategies compatible with context."""

        selected: list[SignalStrategyConfig] = []
        for strategy in self._config.strategies:
            if not strategy.enabled:
                continue
            if strategy.compatible_asset_classes and asset_class.value not in strategy.compatible_asset_classes:
                continue
            if strategy.compatible_regimes and regime.trend.value not in strategy.compatible_regimes:
                continue
            if strategy.horizons and horizon_class.value not in strategy.horizons:
                continue
            selected.append(strategy)
        return selected
