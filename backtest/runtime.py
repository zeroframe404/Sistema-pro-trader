"""Runtime factory helpers used by module 5 scripts and tests."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.audit_journal import AuditJournal
from core.config_models import IndicatorsConfig, RegimeConfig, RiskConfig, SignalsConfig
from core.event_bus import EventBus
from core.logger import get_logger
from data.asset_types import AssetClass
from data.models import OHLCVBar
from execution.adapters.paper_adapter import PaperAdapter
from execution.fill_simulator import FillSimulator
from execution.idempotency import IdempotencyManager
from execution.order_manager import OrderManager
from execution.reconciler import Reconciler
from execution.retry_handler import RetryHandler
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from risk.drawdown_tracker import DrawdownTracker
from risk.exposure_tracker import ExposureTracker
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from risk.slippage_model import SlippageModel
from risk.stop_manager import StopManager
from signals.signal_engine import SignalEngine
from storage.cache_manager import CacheManager
from storage.data_repository import DataRepository
from storage.parquet_store import ParquetStore
from storage.sqlite_store import SQLiteStore


async def build_backtest_runtime(
    *,
    run_id: str,
    data_store_path: Path,
    signals_config: SignalsConfig | None = None,
    risk_config: RiskConfig | None = None,
    indicators_config: IndicatorsConfig | None = None,
) -> tuple[
    EventBus,
    DataRepository,
    IndicatorEngine,
    RegimeDetector,
    SignalEngine,
    RiskManager,
    OrderManager,
]:
    """Build isolated event-driven stack for module 5 backtests."""

    event_bus = EventBus()
    await event_bus.start()

    parquet_store = ParquetStore(base_path=data_store_path)
    sqlite_store = SQLiteStore(db_path=data_store_path / "metadata.sqlite")
    await sqlite_store.initialize()
    cache = CacheManager()
    repository = DataRepository(
        parquet_store=parquet_store,
        sqlite_store=sqlite_store,
        cache_manager=cache,
        connectors={},
        fallback_manager=None,
    )

    cfg_indicators = indicators_config or IndicatorsConfig()
    indicator_engine = IndicatorEngine(
        data_repository=repository,
        cache_enabled=cfg_indicators.indicator_engine.cache_enabled,
        cache_ttl_seconds=cfg_indicators.indicator_engine.cache_ttl_seconds,
        max_lookback_bars=cfg_indicators.indicator_engine.max_lookback_bars,
        backend_preference=cfg_indicators.indicator_engine.backend_preference.value,
    )
    regime_cfg: RegimeConfig = cfg_indicators.regime
    regime_detector = RegimeDetector(
        indicator_engine=indicator_engine,
        data_repository=repository,
        event_bus=event_bus,
        config=regime_cfg,
        run_id=run_id,
    )

    cfg_signals = signals_config or SignalsConfig()
    signal_engine = SignalEngine(
        config=cfg_signals,
        indicator_engine=indicator_engine,
        regime_detector=regime_detector,
        data_repository=repository,
        event_bus=event_bus,
        logger=get_logger("backtest.signal_engine"),
        run_id=run_id,
        audit_journal=AuditJournal(jsonl_path=data_store_path / "audit_backtest_signals.jsonl"),
    )
    await signal_engine.start()

    cfg_risk = risk_config or RiskConfig(enabled=True)
    position_sizer = PositionSizer()
    stop_manager = StopManager()
    drawdown_tracker = DrawdownTracker()
    exposure_tracker = ExposureTracker()
    kill_switch = KillSwitch(config=cfg_risk.kill_switch, event_bus=event_bus, run_id=run_id)
    risk_manager = RiskManager(
        config=cfg_risk,
        position_sizer=position_sizer,
        stop_manager=stop_manager,
        drawdown_tracker=drawdown_tracker,
        exposure_tracker=exposure_tracker,
        kill_switch=kill_switch,
        event_bus=event_bus,
        logger=get_logger("backtest.risk_manager"),
        run_id=run_id,
    )

    slippage = SlippageModel()
    paper_adapter = PaperAdapter(
        initial_balance=cfg_risk.paper.initial_balance,
        fill_simulator=FillSimulator(slippage_model=slippage),
        slippage_model=slippage,
        event_bus=event_bus,
        logger=get_logger("backtest.paper_adapter"),
        run_id=run_id,
        risk_config=cfg_risk,
    )
    order_manager = OrderManager(
        broker_adapter=paper_adapter,
        risk_manager=risk_manager,
        idempotency=IdempotencyManager(data_store_path / "idempotency.sqlite"),
        reconciler=Reconciler(),
        retry_handler=RetryHandler(),
        event_bus=event_bus,
        logger=get_logger("backtest.order_manager"),
        db_path=data_store_path / "oms.sqlite",
        run_id=run_id,
    )
    await order_manager.start()
    return (
        event_bus,
        repository,
        indicator_engine,
        regime_detector,
        signal_engine,
        risk_manager,
        order_manager,
    )


def generate_synthetic_bars(
    *,
    symbol: str,
    broker: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    seed: int = 42,
    base_price: float = 1.1000,
    asset_class: AssetClass = AssetClass.FOREX,
) -> list[OHLCVBar]:
    """Generate deterministic synthetic OHLCV bars for demos/tests."""

    rng = random.Random(seed)
    bars: list[OHLCVBar] = []
    current_time = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    step_seconds = timeframe_seconds(timeframe)
    current_price = base_price
    while current_time < end_utc:
        drift = 0.00002 if (current_time.hour % 2 == 0) else -0.000015
        noise = rng.uniform(-0.0002, 0.0002)
        close = max(current_price + drift + noise, 0.0001)
        high = max(close, current_price) + abs(rng.uniform(0.0, 0.00015))
        low = min(close, current_price) - abs(rng.uniform(0.0, 0.00015))
        volume = 1000.0 + rng.uniform(0.0, 500.0)
        next_time = current_time + timedelta(seconds=step_seconds)
        bars.append(
            OHLCVBar(
                symbol=symbol,
                broker=broker,
                timeframe=timeframe,
                timestamp_open=current_time,
                timestamp_close=next_time,
                open=current_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                spread=0.0001,
                asset_class=asset_class,
                source="synthetic",
            )
        )
        current_price = close
        current_time = next_time
    return bars


def timeframe_seconds(timeframe: str) -> int:
    mapping = {
        "M1": 60,
        "M5": 300,
        "M15": 900,
        "M30": 1800,
        "H1": 3600,
        "H4": 14400,
        "D1": 86400,
        "W1": 604800,
        "MN1": 2592000,
    }
    return mapping.get(timeframe.upper(), 3600)


__all__ = [
    "build_backtest_runtime",
    "generate_synthetic_bars",
    "timeframe_seconds",
]
