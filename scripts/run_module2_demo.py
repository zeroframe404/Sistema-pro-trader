"""Run end-to-end module 2 demo on sample datasets."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from core.config_loader import load_config
from data.asset_types import AssetClass
from data.models import OHLCVBar, Tick
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from scripts.download_sample_data import main as ensure_sample_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run module 2 demo")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--all-assets", action="store_true")
    return parser.parse_args()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _detect_asset_class(symbol: str) -> AssetClass:
    if "BTC" in symbol.upper() or "ETH" in symbol.upper():
        return AssetClass.CRYPTO
    if symbol.upper() in {"EURUSD", "GBPUSD", "USDJPY"}:
        return AssetClass.FOREX
    return AssetClass.STOCK


def load_bars(path: Path, symbol: str) -> list[OHLCVBar]:
    frame = pl.read_parquet(path)
    bars: list[OHLCVBar] = []
    asset_class = _detect_asset_class(symbol)
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
                spread=float(row["spread"]) if row.get("spread") is not None else None,
                asset_class=asset_class,
                source=str(row.get("source", "sample_data")),
            )
        )

    bars.sort(key=lambda item: item.timestamp_open)
    return bars


def _profile_for_symbol(symbol: str) -> str:
    upper = symbol.upper()
    if "BTC" in upper or "ETH" in upper:
        return "crypto"
    if upper.endswith("USD") and len(upper) == 6:
        return "forex"
    return "default"


def _build_indicator_specs(config, profile: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for group in (
        config.indicators.defaults.trend,
        config.indicators.defaults.momentum,
        config.indicators.defaults.volatility,
        config.indicators.defaults.volume,
        config.indicators.defaults.patterns,
    ):
        for item in group:
            if item.enabled:
                specs.append({"id": item.id, "params": item.params})

    override = config.indicators.overrides.get(profile)
    if override is not None and override.enabled:
        for group in (
            override.trend,
            override.momentum,
            override.volatility,
            override.volume,
            override.patterns,
        ):
            for item in group:
                specs.append({"id": item.id, "params": item.params, "enabled": item.enabled})

    return specs


def _print_results(symbol: str, timeframe: str, bars: list[OHLCVBar], summary: dict[str, Any]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title=f"Auto Trading Pro - Modulo 2 Demo ({symbol} {timeframe})")
        table.add_column("Indicador")
        table.add_column("Valor")
        table.add_column("Senal")

        for row in summary["indicators"]:
            table.add_row(row["name"], row["value"], row["signal"])

        console.print(table)
        console.print(
            f"Regimen: {summary['regime']['trend']} | Volatilidad: {summary['regime']['volatility']} "
            f"| Liquidez: {summary['regime']['liquidity']} | Operable: {summary['regime']['is_tradeable']}"
        )
        console.print(f"Barras: {len(bars)}")
    except Exception:
        print(f"Symbol: {symbol} | Timeframe: {timeframe} | Bars: {len(bars)}")
        for row in summary["indicators"]:
            print(f"  - {row['name']}: {row['value']} ({row['signal']})")
        print(f"Regime: {summary['regime']}")


def _save_chart(symbol: str, timeframe: str, bars: list[OHLCVBar], output_path: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    closes = [bar.close for bar in bars]
    timestamps = [bar.timestamp_close for bar in bars]

    plt.figure(figsize=(12, 5))
    plt.plot(timestamps, closes, label="Close", linewidth=1)
    plt.title(f"{symbol} {timeframe} - Close")
    plt.xlabel("Time")
    plt.ylabel("Price")
    plt.grid(alpha=0.3)
    plt.legend()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def run_for_symbol(symbol: str, timeframe: str) -> int:
    sample_map = {
        ("EURUSD", "H1"): Path("tests/validation/sample_data/EURUSD_H1_2024.parquet"),
        ("BTCUSD", "H1"): Path("tests/validation/sample_data/BTCUSD_H1_2024.parquet"),
        ("SPY", "D1"): Path("tests/validation/sample_data/SPY_D1_2024.parquet"),
        ("GLD", "D1"): Path("tests/validation/sample_data/GLD_D1_2024.parquet"),
        ("GGAL", "D1"): Path("tests/validation/sample_data/GGAL_D1_2024.parquet"),
    }

    key = (symbol.upper(), timeframe.upper())
    path = sample_map.get(key)
    if path is None:
        raise ValueError(f"No sample dataset configured for {symbol} {timeframe}")

    if not path.exists():
        ensure_sample_data()

    bars = load_bars(path, symbol=symbol.upper())
    config = load_config(Path("config"))

    indicator_specs = _build_indicator_specs(config, profile=_profile_for_symbol(symbol))
    engine = IndicatorEngine(
        cache_enabled=config.indicators.indicator_engine.cache_enabled,
        cache_ttl_seconds=config.indicators.indicator_engine.cache_ttl_seconds,
        max_lookback_bars=config.indicators.indicator_engine.max_lookback_bars,
        backend_preference=config.indicators.indicator_engine.backend_preference.value,
    )
    batch = asyncio.run(engine.compute_batch(indicator_specs, bars))

    last_bar = bars[-1]
    tick = Tick(
        symbol=last_bar.symbol,
        broker=last_bar.broker,
        timestamp=last_bar.timestamp_close,
        bid=last_bar.close,
        ask=last_bar.close,
        last=last_bar.close,
        volume=last_bar.volume,
        spread=0.0,
        asset_class=last_bar.asset_class,
        source="demo",
    )
    detector = RegimeDetector(indicator_engine=engine, config=config.indicators.regime)
    regime = asyncio.run(detector.detect(bars, current_tick=tick))

    rows = []
    for name in ["RSI", "EMA", "MACD", "ATR", "BOLLINGERBANDS", "ADX", "SUPERTREND"]:
        matches = [item for key_name, item in batch.items() if key_name.upper().startswith(name)]
        if not matches:
            continue
        series = matches[0]
        last_value = series.values[-1]
        signal = "neutral"
        if last_value.extra.get("cross"):
            signal = str(last_value.extra["cross"])
        elif last_value.value is not None:
            signal = "positive" if last_value.value >= 0 else "negative"
        rows.append(
            {
                "name": series.indicator_id,
                "value": "None" if last_value.value is None else f"{last_value.value:.6f}",
                "signal": signal,
            }
        )

    report = {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "bars": len(bars),
        "indicators": rows,
        "regime": regime.model_dump(mode="json"),
        "generated_at": datetime.now(UTC).isoformat(),
    }

    _print_results(symbol.upper(), timeframe.upper(), bars, report)

    out_dir = Path(tempfile.gettempdir())
    json_path = out_dir / f"atp_module2_report_{symbol.upper()}_{timeframe.upper()}.json"
    chart_path = out_dir / f"atp_module2_chart_{symbol.upper()}_{timeframe.upper()}.png"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _save_chart(symbol.upper(), timeframe.upper(), bars, chart_path)

    print(f"[OK] Reporte guardado: {json_path}")
    print(f"[OK] Grafico guardado: {chart_path}")
    print("[OK] Modulo 2 funcionando correctamente")
    return 0


def main() -> int:
    args = parse_args()
    ensure_sample_data()

    if args.all_assets:
        tasks = [
            ("EURUSD", "H1"),
            ("BTCUSD", "H1"),
            ("SPY", "D1"),
            ("GLD", "D1"),
            ("GGAL", "D1"),
        ]
        for symbol, timeframe in tasks:
            code = run_for_symbol(symbol, timeframe)
            if code != 0:
                return code
        return 0

    return run_for_symbol(args.symbol, args.timeframe)


if __name__ == "__main__":
    raise SystemExit(main())

