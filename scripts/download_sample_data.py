"""Download or generate sample OHLCV datasets for validation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

SAMPLE_DIR = Path("tests/validation/sample_data")


def _safe_import_yfinance():
    try:
        import yfinance as yf  # type: ignore[import-not-found]

        return yf
    except Exception:
        return None


def _deterministic_walk(
    *,
    n: int,
    start_price: float,
    seed: int,
    drift: float,
    vol: float,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=drift, scale=vol, size=n)
    prices = np.empty(n, dtype=float)
    prices[0] = start_price
    for idx in range(1, n):
        prices[idx] = max(1e-6, prices[idx - 1] * (1.0 + returns[idx]))
    return prices


def _to_ohlcv(prices: np.ndarray, timeframe: str, start: datetime, step: timedelta) -> pl.DataFrame:
    opens = prices[:-1]
    closes = prices[1:]
    highs = np.maximum(opens, closes) + np.abs(opens - closes) * 0.25
    lows = np.minimum(opens, closes) - np.abs(opens - closes) * 0.25
    volumes = np.linspace(1000.0, 2000.0, num=len(opens), dtype=float)

    ts_open = [start + (i * step) for i in range(len(opens))]
    ts_close = [value + step for value in ts_open]

    return pl.DataFrame(
        {
            "symbol": ["SYNTH"] * len(opens),
            "broker": ["mock"] * len(opens),
            "timeframe": [timeframe] * len(opens),
            "timestamp_open": [value.isoformat() for value in ts_open],
            "timestamp_close": [value.isoformat() for value in ts_close],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "tick_count": [None] * len(opens),
            "spread": [None] * len(opens),
            "asset_class": ["unknown"] * len(opens),
            "source": ["synthetic"] * len(opens),
        }
    )


def _generate_hourly(symbol: str, filename: str, start_price: float, seed: int) -> tuple[Path, int, str]:
    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    n = 8761
    prices = _deterministic_walk(
        n=n,
        start_price=start_price,
        seed=seed,
        drift=0.00001,
        vol=0.001,
    )
    frame = _to_ohlcv(prices, "H1", start, timedelta(hours=1))
    frame = frame.with_columns(pl.lit(symbol).alias("symbol"))
    out = SAMPLE_DIR / filename
    frame.write_parquet(out)
    return out, frame.height, "synthetic"


def _generate_daily(symbol: str, filename: str, start_price: float, seed: int) -> tuple[Path, int, str]:
    start = datetime(2024, 1, 2, 0, 0, tzinfo=UTC)
    n = 253
    prices = _deterministic_walk(
        n=n,
        start_price=start_price,
        seed=seed,
        drift=0.0003,
        vol=0.01,
    )
    frame = _to_ohlcv(prices, "D1", start, timedelta(days=1))
    frame = frame.with_columns(pl.lit(symbol).alias("symbol"))
    frame = frame.head(252)
    out = SAMPLE_DIR / filename
    frame.write_parquet(out)
    return out, frame.height, "synthetic"


def _download_with_yfinance(
    *,
    yf,
    ticker: str,
    interval: str,
    start: str,
    end: str,
    timeframe: str,
    symbol: str,
    filename: str,
) -> tuple[Path, int, str] | None:
    try:
        data = yf.download(
            tickers=ticker,
            start=start,
            end=end,
            interval=interval,
            progress=False,
            auto_adjust=False,
            prepost=False,
        )
    except Exception:
        return None

    if data is None or data.empty:
        return None

    data = data.reset_index()
    ts_col = "Datetime" if "Datetime" in data.columns else "Date"
    if ts_col not in data.columns:
        return None

    timestamp_open = pl.Series(
        [
            value.to_pydatetime().astimezone(UTC).isoformat()
            for value in data[ts_col]
        ]
    )
    step = timedelta(hours=1) if timeframe == "H1" else timedelta(days=1)
    timestamp_close = pl.Series(
        [
            (
                value.to_pydatetime().astimezone(UTC) + step
            ).isoformat()
            for value in data[ts_col]
        ]
    )

    frame = pl.DataFrame(
        {
            "symbol": [symbol] * len(data),
            "broker": ["yfinance"] * len(data),
            "timeframe": [timeframe] * len(data),
            "timestamp_open": timestamp_open,
            "timestamp_close": timestamp_close,
            "open": data["Open"].astype(float).to_list(),
            "high": data["High"].astype(float).to_list(),
            "low": data["Low"].astype(float).to_list(),
            "close": data["Close"].astype(float).to_list(),
            "volume": data["Volume"].fillna(0).astype(float).to_list(),
            "tick_count": [None] * len(data),
            "spread": [None] * len(data),
            "asset_class": ["unknown"] * len(data),
            "source": ["yfinance"] * len(data),
        }
    )

    out = SAMPLE_DIR / filename
    frame.write_parquet(out)
    return out, frame.height, "yfinance"


def main() -> int:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    yf = _safe_import_yfinance()

    results: list[tuple[Path, int, str]] = []

    tasks = [
        ("EURUSD=X", "1h", "2024-01-01", "2025-01-01", "H1", "EURUSD", "EURUSD_H1_2024.parquet"),
        ("BTC-USD", "1h", "2024-01-01", "2025-01-01", "H1", "BTCUSD", "BTCUSD_H1_2024.parquet"),
        ("SPY", "1d", "2024-01-01", "2025-01-01", "D1", "SPY", "SPY_D1_2024.parquet"),
        ("GLD", "1d", "2024-01-01", "2025-01-01", "D1", "GLD", "GLD_D1_2024.parquet"),
        ("GGAL", "1d", "2024-01-01", "2025-01-01", "D1", "GGAL", "GGAL_D1_2024.parquet"),
    ]

    for ticker, interval, start, end, timeframe, symbol, filename in tasks:
        downloaded = None
        if yf is not None:
            downloaded = _download_with_yfinance(
                yf=yf,
                ticker=ticker,
                interval=interval,
                start=start,
                end=end,
                timeframe=timeframe,
                symbol=symbol,
                filename=filename,
            )

        if downloaded is not None:
            results.append(downloaded)
            continue

        if timeframe == "H1":
            seed = abs(hash(symbol)) % (2**32)
            start_price = 1.09 if symbol == "EURUSD" else 40000.0
            results.append(_generate_hourly(symbol, filename, start_price=start_price, seed=seed))
        else:
            seed = abs(hash(symbol)) % (2**32)
            start_price = {
                "SPY": 475.0,
                "GLD": 190.0,
                "GGAL": 28.0,
            }.get(symbol, 100.0)
            results.append(_generate_daily(symbol, filename, start_price=start_price, seed=seed))

    for path, rows, source in results:
        print(f"[OK] {path.name} -> {rows} barras (source: {source})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

