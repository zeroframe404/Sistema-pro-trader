"""Validate regime detection on synthetic trending/ranging datasets."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio

from data.asset_types import AssetClass
from data.models import Tick
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from tests.unit._indicator_fixtures import make_bars


async def _run() -> int:
    detector = RegimeDetector(indicator_engine=IndicatorEngine())

    trend_bars = make_bars([1.0 + i * 0.002 for i in range(240)], timeframe="H1")
    range_bars = make_bars([1.0 for _ in range(240)], timeframe="H1")

    trend_tick = Tick(
        symbol="EURUSD",
        broker="mock",
        timestamp=trend_bars[-1].timestamp_close,
        bid=trend_bars[-1].close,
        ask=trend_bars[-1].close + 0.0001,
        last=trend_bars[-1].close,
        volume=100,
        spread=0.0001,
        asset_class=AssetClass.FOREX,
        source="validation",
    )
    range_tick = trend_tick.model_copy(
        update={
            "timestamp": range_bars[-1].timestamp_close,
            "bid": range_bars[-1].close,
            "ask": range_bars[-1].close + 0.0001,
            "last": range_bars[-1].close,
        }
    )

    trend_regime = await detector.detect(trend_bars, current_tick=trend_tick)
    range_regime = await detector.detect(range_bars, current_tick=range_tick)

    print(f"Trending series regime: {trend_regime.trend.value}")
    print(f"Ranging series regime: {range_regime.trend.value}")

    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())

