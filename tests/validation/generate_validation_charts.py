"""Generate validation charts for module 2 outputs."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path

import numpy as np
import polars as pl

from data.asset_types import AssetClass
from data.models import OHLCVBar, Tick
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from scripts.download_sample_data import main as ensure_sample_data

OUT_DIR = Path("tests/validation/charts")


def _parse_dt(value: str):
    from datetime import UTC, datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _load_bars(path: Path, symbol: str, timeframe: str) -> list[OHLCVBar]:
    frame = pl.read_parquet(path)
    bars: list[OHLCVBar] = []
    for row in frame.to_dicts():
        bars.append(
            OHLCVBar(
                symbol=symbol,
                broker=str(row.get("broker", "mock")),
                timeframe=timeframe,
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


def _save_plot(index: int, title: str, x, y_dict: dict[str, list[float] | np.ndarray]) -> Path:
    import matplotlib.pyplot as plt

    file_path = OUT_DIR / f"{index:02d}_{title}.png"
    plt.figure(figsize=(12, 5))
    for label, values in y_dict.items():
        plt.plot(x, values, label=label)
    plt.title(title)
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(file_path)
    plt.close()
    return file_path


def main() -> int:
    ensure_sample_data()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    bars = _load_bars(Path("tests/validation/sample_data/EURUSD_H1_2024.parquet"), "EURUSD", "H1")
    x = [bar.timestamp_close for bar in bars]
    close = np.asarray([bar.close for bar in bars], dtype=float)

    engine = IndicatorEngine()
    import asyncio

    specs = [
        {"id": "EMA", "params": {"period": 20}},
        {"id": "EMA", "params": {"period": 50}},
        {"id": "EMA", "params": {"period": 200}},
        {"id": "BollingerBands", "params": {"period": 20, "std_dev": 2.0}},
        {"id": "RSI", "params": {"period": 14}},
        {"id": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}},
        {"id": "ADX", "params": {"period": 14}},
        {"id": "SuperTrend", "params": {"atr_period": 10, "multiplier": 3.0}},
        {"id": "SupportResistance", "params": {"method": "fractal", "lookback": 100}},
        {"id": "CandlestickPatterns"},
    ]
    batch = asyncio.run(engine.compute_batch(specs, bars))

    def values(prefix: str) -> list[float]:
        for key, series in batch.items():
            if key.upper().startswith(prefix.upper()):
                return [item.value if item.value is not None else np.nan for item in series.values]
        return [np.nan] * len(bars)

    out_files: list[Path] = []

    out_files.append(
        _save_plot(
            1,
            "ema",
            x,
            {
                "close": close,
                "ema20": values("EMA_period_20"),
                "ema50": values("EMA_period_50"),
                "ema200": values("EMA_period_200"),
            },
        )
    )

    bb_series = next((series for key, series in batch.items() if key.upper().startswith("BOLLINGERBANDS")), None)
    bb_upper = [item.extra.get("upper", np.nan) for item in bb_series.values] if bb_series else [np.nan] * len(bars)
    bb_lower = [item.extra.get("lower", np.nan) for item in bb_series.values] if bb_series else [np.nan] * len(bars)
    out_files.append(_save_plot(2, "bbands", x, {"close": close, "upper": bb_upper, "lower": bb_lower}))

    out_files.append(_save_plot(3, "rsi", x, {"rsi": values("RSI")}))

    macd_series = next((series for key, series in batch.items() if key.upper().startswith("MACD")), None)
    macd_line = [item.extra.get("macd", np.nan) for item in macd_series.values] if macd_series else [np.nan] * len(bars)
    macd_signal = [item.extra.get("signal", np.nan) for item in macd_series.values] if macd_series else [np.nan] * len(bars)
    out_files.append(_save_plot(4, "macd", x, {"macd": macd_line, "signal": macd_signal}))

    adx_series = next((series for key, series in batch.items() if key.upper().startswith("ADX")), None)
    adx = [item.value if item.value is not None else np.nan for item in adx_series.values] if adx_series else [np.nan] * len(bars)
    plus = [item.extra.get("plus_di", np.nan) for item in adx_series.values] if adx_series else [np.nan] * len(bars)
    minus = [item.extra.get("minus_di", np.nan) for item in adx_series.values] if adx_series else [np.nan] * len(bars)
    out_files.append(_save_plot(5, "adx", x, {"adx": adx, "plus_di": plus, "minus_di": minus}))

    out_files.append(_save_plot(6, "supertrend", x, {"close": close, "supertrend": values("SUPERTREND")}))

    out_files.append(
        _save_plot(
            7,
            "ichimoku",
            x,
            {
                "close": close,
                "tenkan": values("ICHIMOKU"),
            },
        )
    )

    out_files.append(_save_plot(8, "sr", x, {"close": close, "sr": values("SUPPORTRESISTANCE")}))
    out_files.append(_save_plot(9, "patterns", x, {"pattern_score": values("CANDLESTICKPATTERNS")}))

    detector = RegimeDetector(indicator_engine=engine)
    regime_vals = []
    for idx in range(120, len(bars), max(1, len(bars) // 120)):
        window = bars[: idx + 1]
        tick = Tick(
            symbol=window[-1].symbol,
            broker=window[-1].broker,
            timestamp=window[-1].timestamp_close,
            bid=window[-1].close,
            ask=window[-1].close,
            last=window[-1].close,
            volume=window[-1].volume,
            spread=0.0,
            asset_class=window[-1].asset_class,
            source="validation",
        )
        regime = asyncio.run(detector.detect(window, current_tick=tick))
        regime_vals.append((window[-1].timestamp_close, regime.trend.value))

    regime_num = {
        "strong_downtrend": -2,
        "weak_downtrend": -1,
        "ranging": 0,
        "weak_uptrend": 1,
        "strong_uptrend": 2,
    }
    out_files.append(
        _save_plot(
            10,
            "regime",
            [item[0] for item in regime_vals],
            {"regime": [regime_num.get(item[1], 0) for item in regime_vals]},
        )
    )

    for idx, file_path in enumerate(out_files, start=1):
        print(f"[OK] Chart {idx:02d} -> {file_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

