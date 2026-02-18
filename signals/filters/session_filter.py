"""Block signals outside liquid market sessions."""

from __future__ import annotations

from data.asset_types import AssetClass
from regime.session_manager import SessionManager
from signals.filters.filter_result import FilterResult
from signals.signal_models import Signal


class SessionFilter:
    """Session quality-based filter."""

    def __init__(self, manager: SessionManager | None = None) -> None:
        self._manager = manager or SessionManager()

    def apply(self, signal: Signal) -> FilterResult:
        raw_asset = signal.metadata.get("asset_class")
        if isinstance(raw_asset, AssetClass):
            asset_class = raw_asset
        elif isinstance(raw_asset, str):
            try:
                asset_class = AssetClass(raw_asset.lower())
            except ValueError:
                asset_class = AssetClass.UNKNOWN
        else:
            asset_class = AssetClass.UNKNOWN

        quality = self._manager.get_session_quality(
            symbol=signal.symbol,
            asset_class=asset_class,
            dt=signal.timestamp,
        )
        if quality >= 0.4:
            return FilterResult(passed=True)
        return FilterResult(passed=False, reason="bad_session")
