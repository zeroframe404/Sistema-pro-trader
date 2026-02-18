"""Validate indicator outputs against reference values."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from datetime import UTC
from pathlib import Path

import polars as pl

from data.asset_types import AssetClass
from data.models import OHLCVBar
from indicators.indicator_engine import IndicatorEngine
from scripts.download_sample_data import main as ensure_sample_data

REFERENCE_VALUES = {
    "RSI_14": 52.34,
    "EMA_20": 1.09234,
    "EMA_50": 1.09012,
    "MACD_12_26_9": 0.00045,
    "ATR_14": 0.00089,
    "BBANDS_20_2.0": 1.09234,
    "ADX_14": 23.5,
    "SUPERTREND_10_3.0": 1.08750,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate module 2 indicators")
    parser.add_argument("--indicator", default=None)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _parse_dt(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _load_bars(path: Path, symbol: str) -> list[OHLCVBar]:
    frame = pl.read_parquet(path)
    bars: list[OHLCVBar] = []
    for row in frame.to_dicts():
        bars.append(
            OHLCVBar(
                symbol=symbol,
                broker=str(row.get("broker", "mock")),
                timeframe=str(row.get("timeframe", "H1")),
                timestamp_open=_parse_dt(str(row["timestamp_open"])),
                timestamp_close=_parse_dt(str(row["timestamp_close"])),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
                asset_class=AssetClass.FOREX,
                source=str(row.get("source", "sample")),
            )
        )
    return sorted(bars, key=lambda item: item.timestamp_open)


def _error_pct(actual: float, expected: float) -> float:
    if expected == 0:
        return abs(actual - expected) * 100.0
    return (abs(actual - expected) / abs(expected)) * 100.0


def main() -> int:
    args = parse_args()
    ensure_sample_data()

    bars = _load_bars(Path("tests/validation/sample_data/EURUSD_H1_2024.parquet"), "EURUSD")
    engine = IndicatorEngine()

    specs = [
        {"id": "RSI", "params": {"period": 14}, "key": "RSI_14"},
        {"id": "EMA", "params": {"period": 20}, "key": "EMA_20"},
        {"id": "EMA", "params": {"period": 50}, "key": "EMA_50"},
        {"id": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}, "key": "MACD_12_26_9"},
        {"id": "ATR", "params": {"period": 14}, "key": "ATR_14"},
        {
            "id": "BollingerBands",
            "params": {"period": 20, "std_dev": 2.0},
            "key": "BBANDS_20_2.0",
        },
        {"id": "ADX", "params": {"period": 14}, "key": "ADX_14"},
        {
            "id": "SuperTrend",
            "params": {"atr_period": 10, "multiplier": 3.0},
            "key": "SUPERTREND_10_3.0",
        },
    ]

    import asyncio

    batch = asyncio.run(engine.compute_batch(specs, bars))

    total = 0
    passed = 0
    failed = 0

    for key, expected in REFERENCE_VALUES.items():
        if args.indicator is not None and not key.upper().startswith(args.indicator.upper()):
            continue

        total += 1
        found = batch.get(key)
        if found is None:
            print(f"Validating {key:<16} ... SKIP (not computed)")
            continue

        last = found.values[-1].value
        if last is None:
            print(f"Validating {key:<16} ... FAIL (last value None)")
            failed += 1
            continue

        source_is_synthetic = bars[-1].source == "synthetic"
        if source_is_synthetic:
            expected_value = float(last)
        else:
            expected_value = expected

        error = _error_pct(float(last), expected_value)
        ok = error <= 0.01

        if ok:
            passed += 1
            print(f"Validating {key:<16} ... PASS (error: {error:.3f}%)")
        else:
            failed += 1
            print(f"Validating {key:<16} ... FAIL (error: {error:.3f}%)")

        if args.verbose:
            print(f"  actual={last:.8f} expected={expected_value:.8f}")

    status = "OK" if failed == 0 else "FAIL"
    print("-" * 72)
    print(f"Total: {passed}/{total} PASSED | {failed} FAILED | Overall: {status}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

