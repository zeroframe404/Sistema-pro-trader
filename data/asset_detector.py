"""Automatic asset discovery and classification."""

from __future__ import annotations

from typing import Any

from data.asset_classifier import AssetClassifier
from data.asset_types import AssetClass
from data.models import AssetInfo


class AssetDetector:
    """Detect available assets from connectors and classify symbols."""

    def __init__(self) -> None:
        self._classifier = AssetClassifier()

    async def detect_from_mt5(self, connector: Any) -> list[AssetInfo]:
        """Detect assets from an MT5 connector."""

        assets = await connector.get_available_symbols()
        return self._classify_assets(assets=assets, broker=connector.broker)

    async def detect_from_tradingview(self, connector: Any) -> list[AssetInfo]:
        """Detect assets from a TradingView connector-like source."""

        assets = await connector.get_available_symbols()
        return self._classify_assets(assets=assets, broker=connector.broker)

    async def detect_from_broker(self, connector: Any) -> list[AssetInfo]:
        """Detect and classify assets from any DataConnector implementation."""

        assets = await connector.get_available_symbols()
        return self._classify_assets(assets=assets, broker=connector.broker)

    def classify_symbol(
        self,
        symbol: str,
        broker: str,
        metadata: dict[str, Any] | None = None,
    ) -> AssetClass:
        """Classify a symbol using shared heuristics."""

        return self._classifier.classify_symbol(symbol=symbol, broker=broker, metadata=metadata)

    def _classify_assets(self, assets: list[AssetInfo], broker: str) -> list[AssetInfo]:
        result: list[AssetInfo] = []
        for asset in assets:
            metadata = dict(asset.extra)
            classified = self.classify_symbol(asset.symbol, broker=broker, metadata=metadata)
            result.append(asset.model_copy(update={"asset_class": classified}))
        return result
