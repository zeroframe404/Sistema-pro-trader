"""Block signals around scheduled macro-news windows."""

from __future__ import annotations

from datetime import UTC

from data.asset_types import AssetClass
from regime.news_window_detector import NewsWindowDetector
from signals.filters.filter_result import FilterResult
from signals.signal_models import Signal


class NewsFilter:
    """News window filter wrapper."""

    def __init__(self, detector: NewsWindowDetector | None = None) -> None:
        self._detector = detector or NewsWindowDetector()

    async def warmup(self) -> None:
        """Preload near-term events cache."""

        await self._detector.fetch_upcoming_events(hours_ahead=48)

    def apply(self, signal: Signal, asset_class: AssetClass) -> FilterResult:
        """Return fail if signal falls in protected news window."""

        in_window, event = self._detector.is_in_news_window(
            symbol=signal.symbol,
            asset_class=asset_class,
            now=signal.timestamp.astimezone(UTC),
        )
        if not in_window:
            return FilterResult(passed=True)

        event_id = event.event_id if event is not None else "unknown"
        return FilterResult(passed=False, reason=f"news_window_{event_id}")
