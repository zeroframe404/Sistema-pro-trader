"""Module 3 demo runner: full signal pipeline on sample datasets."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib.pyplot as plt
import polars as pl
from rich.console import Console
from rich.table import Table

from core.config_models import BrokerConfig, SignalsConfig
from core.event_bus import EventBus
from core.logger import configure_logging, get_logger
from data.asset_types import AssetClass
from data.connectors.mock_connector import MockConnector
from data.feed_manager import FeedManager
from data.models import OHLCVBar
from data.normalizer import Normalizer
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from signals.signal_engine import SignalEngine

ASSET_FILES: dict[str, tuple[str, str, AssetClass]] = {
    "EURUSD": ("EURUSD_H1_2024.parquet", "H1", AssetClass.FOREX),
    "BTCUSD": ("BTCUSD_H1_2024.parquet", "H1", AssetClass.CRYPTO),
    "GGAL": ("GGAL_D1_2024.parquet", "D1", AssetClass.CEDEAR),
    "SPY": ("SPY_D1_2024.parquet", "D1", AssetClass.ETF),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run module3 signal demo")
    parser.add_argument("--symbol", type=str, default="EURUSD")
    parser.add_argument("--horizon", type=str, default="2 horas")
    parser.add_argument("--all-assets", action="store_true")
    return parser.parse_args()


def _to_bar_rows(path: Path, symbol: str, timeframe: str, asset_class: AssetClass) -> list[OHLCVBar]:
    frame = pl.read_parquet(path).sort("timestamp_open")
    rows = frame.to_dicts()
    bars: list[OHLCVBar] = []
    for row in rows:
        bars.append(
            OHLCVBar(
                symbol=symbol,
                broker="mock_dev",
                timeframe=timeframe,
                timestamp_open=_dt(row["timestamp_open"]),
                timestamp_close=_dt(row["timestamp_close"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
                spread=float(row["spread"]) if row.get("spread") is not None else 0.0,
                source="demo",
                asset_class=asset_class,
            )
        )
    return bars


def _dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise TypeError(f"Unsupported datetime: {value!r}")


async def _run_single(symbol: str, horizon: str, console: Console) -> int:
    if symbol not in ASSET_FILES:
        console.print(f"[red]Symbol not supported in sample_data: {symbol}[/red]")
        return 1

    file_name, timeframe, asset_class = ASSET_FILES[symbol]
    bars = _to_bar_rows(
        Path("tests/validation/sample_data") / file_name,
        symbol,
        timeframe,
        asset_class,
    )

    run_id = str(uuid4())
    configure_logging(run_id=run_id, environment="development", log_level="INFO")
    event_bus = EventBus()
    await event_bus.start()
    connector = MockConnector(
        config=BrokerConfig(
            broker_id="mock_dev",
            broker_type="mock",
            enabled=True,
            paper_mode=True,
            extra={},
        ),
        event_bus=event_bus,
        normalizer=Normalizer(),
        logger=get_logger("demo.mock_connector"),
        run_id=run_id,
        ohlcv_data={symbol: bars},
        latency_ms=0.0,
    )
    feed_manager = FeedManager(
        connectors=[connector],
        event_bus=event_bus,
        run_id=run_id,
        data_store_path=Path("data_store"),
        logger=get_logger("demo.feed_manager"),
    )
    await feed_manager.start()

    try:
        indicator_engine = IndicatorEngine(data_repository=feed_manager.get_repository())
        regime_detector = RegimeDetector(
            indicator_engine=indicator_engine,
            data_repository=feed_manager.get_repository(),
            event_bus=event_bus,
            run_id=run_id,
        )
        signal_engine = SignalEngine(
            config=SignalsConfig(),
            indicator_engine=indicator_engine,
            regime_detector=regime_detector,
            data_repository=feed_manager.get_repository(),
            event_bus=event_bus,
            logger=get_logger("demo.signal_engine"),
            run_id=run_id,
        )
        await signal_engine.start()

        decision = await signal_engine.get_decision_for_user(
            symbol=symbol,
            broker="mock_dev",
            horizon_input=horizon,
            asset_class=asset_class,
        )

        _render_console(console, decision)
        report_path = _write_report(symbol, decision)
        chart_path = _write_chart(symbol, bars)
        console.print(f"[green]Reporte:[/green] {report_path}")
        console.print(f"[green]Grafico:[/green] {chart_path}")
    finally:
        await feed_manager.stop()
        await event_bus.stop()

    return 0


def _render_console(console: Console, decision) -> None:
    table = Table(title=f"Analisis {decision.ensemble.symbol}")
    table.add_column("Decision")
    table.add_column("Confianza")
    table.add_column("Regimen")
    table.add_row(
        decision.display_decision,
        f"{decision.confidence_percent}%",
        f"{decision.ensemble.regime.trend.value}/{decision.ensemble.regime.volatility.value}",
    )
    console.print(table)
    if decision.top_reasons:
        console.print("Razones principales:")
        for reason in decision.top_reasons[:5]:
            console.print(f" - {reason.factor}: {reason.description} ({int(reason.weight*100)}%)")


def _write_report(symbol: str, decision) -> Path:
    out = Path(gettempdir()) / f"atp_module3_report_{symbol}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(decision.model_dump(mode="json"), indent=2), encoding="utf-8")
    return out


def _write_chart(symbol: str, bars: list[OHLCVBar]) -> Path:
    out = Path(gettempdir()) / f"atp_module3_chart_{symbol}_{bars[-1].timeframe}.png"
    ts = [item.timestamp_open for item in bars[-300:]]
    close = [item.close for item in bars[-300:]]
    plt.figure(figsize=(12, 5))
    plt.plot(ts, close, linewidth=1.2)
    plt.title(f"{symbol} close series")
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close()
    return out


async def _main() -> int:
    args = _parse_args()
    console = Console()
    console.print("[bold]Auto Trading Pro - Modulo 3 Demo[/bold]")
    if args.all_assets:
        exit_code = 0
        for symbol in ("EURUSD", "BTCUSD", "GGAL", "SPY"):
            code = await _run_single(symbol, args.horizon, console)
            exit_code = max(exit_code, code)
        return exit_code
    return await _run_single(args.symbol.upper(), args.horizon, console)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
