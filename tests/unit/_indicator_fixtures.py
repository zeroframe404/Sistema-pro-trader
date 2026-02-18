from __future__ import annotations

from datetime import UTC, datetime, timedelta

from data.asset_types import AssetClass
from data.models import OHLCVBar


def make_bars(
    closes: list[float],
    *,
    symbol: str = "EURUSD",
    timeframe: str = "M1",
    start: datetime | None = None,
) -> list[OHLCVBar]:
    if start is None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    bars: list[OHLCVBar] = []
    current_open = start
    prev_close = closes[0]
    for close in closes:
        open_price = prev_close
        high = max(open_price, close) + 0.05
        low = min(open_price, close) - 0.05
        bar = OHLCVBar(
            symbol=symbol,
            broker="mock",
            timeframe=timeframe,
            timestamp_open=current_open,
            timestamp_close=current_open + timedelta(minutes=1 if timeframe == "M1" else 60),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=100.0,
            spread=0.0001,
            asset_class=AssetClass.FOREX,
            source="test",
        )
        bars.append(bar)
        current_open = bar.timestamp_close
        prev_close = close
    return bars
