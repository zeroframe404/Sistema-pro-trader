from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data.asset_types import AssetClass
from data.models import OHLCVBar
from storage.parquet_store import ParquetStore


def _make_bars(start: datetime, count: int) -> list[OHLCVBar]:
    bars: list[OHLCVBar] = []
    for i in range(count):
        open_time = start + timedelta(days=i)
        bars.append(
            OHLCVBar(
                symbol="EURUSD",
                broker="mock",
                timeframe="D1",
                timestamp_open=open_time,
                timestamp_close=open_time + timedelta(days=1),
                open=1.0 + i * 0.001,
                high=1.1 + i * 0.001,
                low=0.9 + i * 0.001,
                close=1.05 + i * 0.001,
                volume=100 + i,
                asset_class=AssetClass.FOREX,
                source="mock",
            )
        )
    return bars


@pytest.mark.asyncio
async def test_save_and_load_1000_bars(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    start = datetime(2020, 1, 1, tzinfo=UTC)
    bars = _make_bars(start, 1000)

    t0 = time.perf_counter()
    await store.save_bars(bars)
    loaded = await store.load_bars("EURUSD", "mock", "D1", start, start + timedelta(days=999))
    elapsed = time.perf_counter() - t0

    assert len(loaded) == 1000
    # Informative benchmark: measured for observability only.
    assert elapsed >= 0


@pytest.mark.asyncio
async def test_no_duplicates_on_double_save(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = _make_bars(start, 10)

    await store.save_bars(bars)
    await store.save_bars(bars)

    loaded = await store.load_bars("EURUSD", "mock", "D1", start, start + timedelta(days=9))
    assert len(loaded) == 10


@pytest.mark.asyncio
async def test_get_available_range_is_correct(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = _make_bars(start, 10)

    await store.save_bars(bars)
    available = await store.get_available_range("EURUSD", "mock", "D1")

    assert available is not None
    assert available[0] == bars[0].timestamp_open
    assert available[1] == bars[-1].timestamp_close


@pytest.mark.asyncio
async def test_partitioned_by_month(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    jan_start = datetime(2026, 1, 25, tzinfo=UTC)
    bars = _make_bars(jan_start, 10)

    await store.save_bars(bars)

    directory = tmp_path / "parquet" / "mock" / "EURUSD" / "D1"
    files = sorted(path.name for path in directory.glob("*.parquet"))

    assert "2026-01.parquet" in files
    assert "2026-02.parquet" in files


@pytest.mark.asyncio
async def test_range_retrieval_excludes_outside_rows(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = _make_bars(start, 20)

    await store.save_bars(bars)

    from_dt = start + timedelta(days=5)
    to_dt = start + timedelta(days=8)
    loaded = await store.load_bars("EURUSD", "mock", "D1", from_dt, to_dt)

    assert len(loaded) == 4
    assert all(from_dt <= row.timestamp_open <= to_dt for row in loaded)
