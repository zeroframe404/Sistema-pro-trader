"""Parquet storage for normalized OHLCV history."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from data.models import OHLCVBar


class ParquetStore:
    """Persist OHLCV bars in monthly-partitioned parquet files."""

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path / "parquet"
        self._base_path.mkdir(parents=True, exist_ok=True)

    async def save_bars(self, bars: list[OHLCVBar]) -> None:
        """Save bars with deduplication on timestamp_open per file partition."""

        if not bars:
            return

        grouped: dict[Path, list[OHLCVBar]] = {}
        for bar in bars:
            grouped.setdefault(self._file_path_for_bar(bar), []).append(bar)

        for file_path, batch in grouped.items():
            existing = self._read_bars_from_file(file_path)
            merged_by_open: dict[str, OHLCVBar] = {
                item.timestamp_open.isoformat(): item for item in existing
            }
            for item in batch:
                merged_by_open[item.timestamp_open.isoformat()] = item

            merged = sorted(merged_by_open.values(), key=lambda item: item.timestamp_open)
            self._write_bars_to_file(file_path, merged)

    async def load_bars(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Load bars in datetime range."""

        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        files = self._files_for_range(symbol, broker, timeframe, start_utc, end_utc)

        result: list[OHLCVBar] = []
        for file_path in files:
            for bar in self._read_bars_from_file(file_path):
                if start_utc <= bar.timestamp_open <= end_utc:
                    result.append(bar)

        return sorted(result, key=lambda item: item.timestamp_open)

    async def get_available_range(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
    ) -> tuple[datetime, datetime] | None:
        """Return available datetime range for one symbol/broker/timeframe."""

        target_dir = self._base_path / broker / symbol / timeframe
        if not target_dir.exists():
            return None

        mins: list[datetime] = []
        maxs: list[datetime] = []
        for file_path in sorted(target_dir.glob("*.parquet")):
            bars = self._read_bars_from_file(file_path)
            if not bars:
                continue
            mins.append(bars[0].timestamp_open)
            maxs.append(bars[-1].timestamp_close)

        if not mins:
            return None
        return min(mins), max(maxs)

    async def delete_bars(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """Delete bars in datetime range and return removed count."""

        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        files = self._files_for_range(symbol, broker, timeframe, start_utc, end_utc)

        removed = 0
        for file_path in files:
            bars = self._read_bars_from_file(file_path)
            kept: list[OHLCVBar] = []
            for bar in bars:
                if start_utc <= bar.timestamp_open <= end_utc:
                    removed += 1
                    continue
                kept.append(bar)

            if kept:
                self._write_bars_to_file(file_path, kept)
            else:
                file_path.unlink(missing_ok=True)

        return removed

    def get_storage_stats(self) -> dict[str, int]:
        """Return storage level file and size statistics."""

        files = list(self._base_path.rglob("*.parquet"))
        size = sum(item.stat().st_size for item in files)

        assets: set[str] = set()
        for file_path in files:
            parts = file_path.parts
            if len(parts) >= 4:
                assets.add(parts[-3])

        return {
            "file_count": len(files),
            "size_bytes": size,
            "asset_count": len(assets),
        }

    def _file_path_for_bar(self, bar: OHLCVBar) -> Path:
        month_key = bar.timestamp_open.astimezone(UTC).strftime("%Y-%m")
        directory = self._base_path / bar.broker / bar.symbol / bar.timeframe
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{month_key}.parquet"

    def _files_for_range(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Path]:
        directory = self._base_path / broker / symbol / timeframe
        if not directory.exists():
            return []

        files: list[Path] = []
        cursor = datetime(start.year, start.month, 1, tzinfo=UTC)
        end_month = datetime(end.year, end.month, 1, tzinfo=UTC)

        while cursor <= end_month:
            files.append(directory / f"{cursor.strftime('%Y-%m')}.parquet")
            if cursor.month == 12:
                cursor = datetime(cursor.year + 1, 1, 1, tzinfo=UTC)
            else:
                cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=UTC)

        return [item for item in files if item.exists()]

    def _read_bars_from_file(self, file_path: Path) -> list[OHLCVBar]:
        if not file_path.exists():
            return []

        frame = pl.read_parquet(file_path)
        bars: list[OHLCVBar] = []
        for row in frame.to_dicts():
            bars.append(
                OHLCVBar(
                    symbol=str(row["symbol"]),
                    broker=str(row["broker"]),
                    timeframe=str(row["timeframe"]),
                    timestamp_open=self._parse_dt(row["timestamp_open"]),
                    timestamp_close=self._parse_dt(row["timestamp_close"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    tick_count=int(row["tick_count"]) if row.get("tick_count") is not None else None,
                    spread=float(row["spread"]) if row.get("spread") is not None else None,
                    asset_class=row["asset_class"],
                    source=str(row["source"]),
                )
            )

        return sorted(bars, key=lambda item: item.timestamp_open)

    def _write_bars_to_file(self, file_path: Path, bars: list[OHLCVBar]) -> None:
        rows = [
            {
                "symbol": bar.symbol,
                "broker": bar.broker,
                "timeframe": bar.timeframe,
                "timestamp_open": bar.timestamp_open.astimezone(UTC).isoformat(),
                "timestamp_close": bar.timestamp_close.astimezone(UTC).isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "tick_count": bar.tick_count,
                "spread": bar.spread,
                "asset_class": bar.asset_class.value,
                "source": bar.source,
            }
            for bar in bars
        ]

        if not rows:
            file_path.unlink(missing_ok=True)
            return

        frame = pl.DataFrame(rows)
        frame.write_parquet(file_path)

    @staticmethod
    def _parse_dt(value: object) -> datetime:
        if isinstance(value, datetime):
            return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        raise TypeError(f"Unsupported datetime value: {value!r}")
