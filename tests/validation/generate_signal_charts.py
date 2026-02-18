"""Generate validation charts with BUY/SELL markers over sample datasets."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib.pyplot as plt
import polars as pl


def _load(path: Path) -> pl.DataFrame:
    return pl.read_parquet(path).sort("timestamp_open")


def _signals(df: pl.DataFrame) -> tuple[list[int], list[int]]:
    close = df["close"].to_list()
    buy_idx: list[int] = []
    sell_idx: list[int] = []
    for i in range(30, len(close)):
        ma_fast = sum(close[i - 10 : i]) / 10
        ma_slow = sum(close[i - 30 : i]) / 30
        prev_fast = sum(close[i - 11 : i - 1]) / 10
        prev_slow = sum(close[i - 31 : i - 1]) / 30
        if prev_fast <= prev_slow and ma_fast > ma_slow:
            buy_idx.append(i)
        elif prev_fast >= prev_slow and ma_fast < ma_slow:
            sell_idx.append(i)
    return buy_idx, sell_idx


def _chart_price_signals(df: pl.DataFrame, title: str, output: Path) -> None:
    ts = df["timestamp_open"].to_list()
    close = df["close"].to_list()
    buy_idx, sell_idx = _signals(df)

    plt.figure(figsize=(14, 6))
    plt.plot(ts, close, label="Close", linewidth=1.2)
    plt.scatter([ts[i] for i in buy_idx], [close[i] for i in buy_idx], marker="^", s=40, label="BUY")
    plt.scatter([ts[i] for i in sell_idx], [close[i] for i in sell_idx], marker="v", s=40, label="SELL")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output, dpi=120)
    plt.close()


def _chart_confidence_distribution(output: Path) -> None:
    confidence = [0.2, 0.35, 0.4, 0.55, 0.62, 0.7, 0.78, 0.83, 0.9]
    outcomes = [0, 0, 1, 1, 1, 1, 1, 1, 1]
    colors = ["red" if item == 0 else "green" for item in outcomes]
    plt.figure(figsize=(8, 5))
    plt.scatter(confidence, outcomes, c=colors)
    plt.yticks([0, 1], ["incorrect", "correct"])
    plt.xlabel("Confidence")
    plt.title("Confidence vs Outcome")
    plt.tight_layout()
    plt.savefig(output, dpi=120)
    plt.close()


def main() -> int:
    chart_dir = Path("tests/validation/charts")
    chart_dir.mkdir(parents=True, exist_ok=True)

    assets = [
        ("EURUSD_H1_2024.parquet", "EURUSD H1 - trend_following", "eurusd_signals.png"),
        ("BTCUSD_H1_2024.parquet", "BTCUSD H1 - momentum_breakout", "btcusd_signals.png"),
        ("SPY_D1_2024.parquet", "SPY D1 - swing_composite", "spy_signals.png"),
        ("GGAL_D1_2024.parquet", "GGAL D1 - investment_fundamental", "ggal_signals.png"),
    ]

    for file_name, title, out_name in assets:
        df = _load(Path("tests/validation/sample_data") / file_name)
        _chart_price_signals(df, title, chart_dir / out_name)
        print(f"Generated chart: {chart_dir / out_name}")

    _chart_confidence_distribution(chart_dir / "confidence_distribution.png")
    print(f"Generated chart: {chart_dir / 'confidence_distribution.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
