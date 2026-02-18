"""Signal engine orchestration for Module 3."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from structlog.stdlib import BoundLogger

from core.audit_journal import AuditJournal, JournalEntry
from core.config_models import SignalsConfig
from core.event_bus import EventBus
from core.events import BarCloseEvent, SignalEvent
from data.asset_types import AssetClass
from data.models import OHLCVBar, Tick
from data.resampler import Resampler
from indicators.indicator_engine import IndicatorEngine
from regime.regime_detector import RegimeDetector
from regime.regime_models import LiquidityRegime, MarketRegime, TrendRegime, VolatilityRegime
from signals.anti_overtrading import AntiOvertradingGuard
from signals.asset_strategy_selector import AssetStrategySelector
from signals.confidence_scorer import ConfidenceScorer
from signals.ensemble import SignalEnsemble
from signals.filters import CorrelationFilter, NewsFilter, RegimeFilter, SessionFilter, SpreadFilter
from signals.horizon_adapter import HorizonAdapter
from signals.signal_explainer import SignalExplainer
from signals.signal_models import (
    DecisionResult,
    EnsembleResult,
    Signal,
    SignalDirection,
    SignalReason,
    SignalStrength,
)
from signals.strategies import (
    InvestmentFundamentalStrategy,
    MeanReversionStrategy,
    MomentumBreakoutStrategy,
    RangeScalpStrategy,
    ScalpingReversalStrategy,
    SignalStrategy,
    SwingCompositeStrategy,
    TrendFollowingStrategy,
)
from storage.data_repository import DataRepository


class SignalEngine:
    """Single entry point for signal generation and explanation."""

    def __init__(
        self,
        *,
        config: SignalsConfig,
        indicator_engine: IndicatorEngine,
        regime_detector: RegimeDetector,
        data_repository: DataRepository,
        event_bus: EventBus,
        logger: BoundLogger,
        run_id: str,
        audit_journal: AuditJournal | None = None,
    ) -> None:
        self._config = config
        self._indicator_engine = indicator_engine
        self._regime_detector = regime_detector
        self._data_repository = data_repository
        self._event_bus = event_bus
        self._logger = logger
        self._run_id = run_id
        self._journal = audit_journal or AuditJournal(jsonl_path=Path("data_store") / "audit_signals.jsonl")

        self._resampler = Resampler()
        self._ensemble = SignalEnsemble(
            strategy_weights={item.strategy_id: item.weight for item in config.strategies},
            wait_threshold=config.ensemble.wait_threshold,
            contradiction_threshold=config.ensemble.contradiction_threshold,
        )
        self._confidence_scorer = ConfidenceScorer(config.confidence)
        self._explainer = SignalExplainer()
        self._anti = AntiOvertradingGuard(config.anti_overtrading)
        self._horizon_adapter = HorizonAdapter()
        self._selector = AssetStrategySelector(config)

        self._regime_filter = RegimeFilter()
        self._news_filter = NewsFilter()
        self._session_filter = SessionFilter()
        self._spread_filter = SpreadFilter(config.filters.max_spread_multiplier)
        self._corr_filter = CorrelationFilter(
            window_minutes=config.filters.correlation_window_minutes,
            group_limit=config.filters.correlation_group_limit,
        )

        self._active_signals: list[Signal] = []
        self._signal_history: deque[Signal] = deque(maxlen=config.engine.signal_history_limit)
        self._lock = asyncio.Lock()

        self._strategy_map: dict[str, type[SignalStrategy]] = {
            "trend_following": TrendFollowingStrategy,
            "mean_reversion": MeanReversionStrategy,
            "momentum_breakout": MomentumBreakoutStrategy,
            "scalping_reversal": ScalpingReversalStrategy,
            "swing_composite": SwingCompositeStrategy,
            "investment_fundamental": InvestmentFundamentalStrategy,
            "range_scalp": RangeScalpStrategy,
        }
        self._strategies: dict[str, SignalStrategy] = {}
        for strategy_cfg in config.strategies:
            strategy_cls = self._strategy_map.get(strategy_cfg.strategy_id)
            if strategy_cls is None:
                continue
            self._strategies[strategy_cfg.strategy_id] = strategy_cls(config=strategy_cfg, run_id=run_id)

    async def start(self) -> None:
        """Warm up optional filter caches."""

        await self._news_filter.warmup()

    async def analyze(
        self,
        symbol: str,
        broker: str,
        timeframe: str,
        horizon: str,
        asset_class: AssetClass | None = None,
        as_of: datetime | None = None,
    ) -> DecisionResult:
        """Run full analysis pipeline for one symbol/timeframe."""

        lookback_bars = self._config.engine.default_lookback_bars
        tf_seconds = self._resampler.get_timeframe_seconds(timeframe)
        end = as_of.astimezone(UTC) if as_of is not None else datetime.now(UTC)
        start = end - timedelta(seconds=tf_seconds * lookback_bars)

        bars = await self._data_repository.get_ohlcv(
            symbol=symbol,
            broker=broker,
            timeframe=timeframe,
            start=start,
            end=end,
            auto_fetch=True,
        )
        if not bars:
            regime = self._default_regime(symbol=symbol, timeframe=timeframe, timestamp=end)
            ensemble = self._ensemble.combine([], regime=regime, method=self._config.ensemble.method.value)
            return self._to_decision(ensemble=ensemble, asset_class=asset_class or AssetClass.UNKNOWN)

        resolved_asset_class = asset_class or bars[-1].asset_class
        synthetic_tick = Tick(
            symbol=symbol,
            broker=broker,
            timestamp=bars[-1].timestamp_close,
            bid=bars[-1].close,
            ask=bars[-1].close,
            last=bars[-1].close,
            volume=bars[-1].volume,
            spread=bars[-1].spread if bars[-1].spread is not None else 0.0,
            asset_class=resolved_asset_class,
            source="signal_engine",
        )
        regime = await self._regime_detector.detect(bars=bars, current_tick=synthetic_tick)

        horizon_selection = self._horizon_adapter.parse_horizon(horizon, resolved_asset_class)
        selected_configs = self._selector.select(
            asset_class=resolved_asset_class,
            regime=regime,
            horizon_class=horizon_selection.horizon_class,
        )

        signals: list[Signal] = []
        blocked_filters: list[str] = []
        passed_filters: list[str] = []

        for strategy_cfg in selected_configs:
            strategy = self._strategies.get(strategy_cfg.strategy_id)
            if strategy is None:
                continue
            signal = await strategy.generate(
                symbol=symbol,
                broker=broker,
                timeframe=timeframe,
                horizon=horizon_selection.canonical_horizon,
                bars=bars,
                regime=regime,
                timestamp=bars[-1].timestamp_close,
            )
            if signal is None:
                continue

            signal = signal.model_copy(
                update={
                    "metadata": {**signal.metadata, "asset_class": resolved_asset_class.value},
                }
            )

            filter_result = self._apply_filters(signal=signal, asset_class=resolved_asset_class, bars=bars)
            if not filter_result[0]:
                blocked_filters.extend(filter_result[1])
                continue

            adjusted_signal = signal.model_copy(update={"confidence": min(1.0, signal.confidence * filter_result[2])})
            signals.append(adjusted_signal)
            passed_filters.extend(filter_result[3])

        ensemble_method = self._config.ensemble.method.value
        ensemble = self._ensemble.combine(signals, regime=regime, method=ensemble_method)
        ensemble.filters_blocked = sorted(set(blocked_filters))
        ensemble.filters_passed = sorted(set(passed_filters))

        adjusted_confidence = self._confidence_scorer.score(ensemble)
        ensemble.final_confidence = adjusted_confidence
        ensemble.final_strength = self._confidence_scorer.strength_for(adjusted_confidence)
        ensemble.short_explanation = self._explainer.explain_notification(ensemble)
        ensemble.explanation = self._explainer.explain_full(ensemble)

        decision = self._to_decision(ensemble=ensemble, asset_class=resolved_asset_class)
        await self._register_and_emit(decision, timeframe_seconds=tf_seconds)
        return decision

    async def analyze_multi_timeframe(
        self,
        symbol: str,
        broker: str,
        timeframes: list[str],
        horizon: str,
        as_of: datetime | None = None,
    ) -> dict[str, DecisionResult]:
        """Analyze one symbol across multiple timeframes."""

        results: dict[str, DecisionResult] = {}
        for timeframe in timeframes:
            results[timeframe] = await self.analyze(
                symbol=symbol,
                broker=broker,
                timeframe=timeframe,
                horizon=horizon,
                as_of=as_of,
            )
        return results

    async def on_bar_close(self, event: BarCloseEvent) -> None:
        """BAR_CLOSE subscriber entrypoint."""

        if not self._config.enabled or not self._config.engine.enabled or not self._config.engine.emit_on_bar_close:
            return
        await self.analyze(
            symbol=event.symbol,
            broker=event.broker,
            timeframe=event.timeframe,
            horizon=self._config.horizon.default_horizon,
            as_of=event.timestamp_close,
        )

    async def get_decision_for_user(
        self,
        symbol: str,
        broker: str,
        horizon_input: str,
        asset_class: AssetClass | None = None,
    ) -> DecisionResult:
        """Natural-language horizon front door."""

        selection = self._horizon_adapter.parse_horizon(horizon_input, asset_class)
        return await self.analyze(
            symbol=symbol,
            broker=broker,
            timeframe=selection.timeframe,
            horizon=selection.canonical_horizon,
            asset_class=asset_class,
        )

    def get_active_signals(self) -> list[Signal]:
        """Return non-expired active signals."""

        now = datetime.now(UTC)
        self._active_signals = [signal for signal in self._active_signals if signal.expires_at is None or signal.expires_at > now]
        return list(self._active_signals)

    async def get_signal_history(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[Signal]:
        """Return historical signals from memory with journal fallback."""

        history = list(self._signal_history)
        if symbol is not None:
            history = [item for item in history if item.symbol == symbol]
        if history:
            return history[-limit:]

        entries = await self._journal.query(symbol=symbol, strategy_id="signal_ensemble")
        results: list[Signal] = []
        for entry in entries[-limit:]:
            regime_data = entry.scores.get("regime", {})
            regime = self._default_regime(
                symbol=entry.symbol,
                timeframe=entry.timeframe,
                timestamp=entry.timestamp.astimezone(UTC),
            ).model_copy(update=regime_data if isinstance(regime_data, dict) else {})
            results.append(
                Signal(
                    signal_id=entry.entry_id,
                    strategy_id=entry.strategy_id,
                    strategy_version=entry.strategy_version,
                    symbol=entry.symbol,
                    broker=str(entry.raw_inputs.get("broker", "unknown")),
                    timeframe=entry.timeframe,
                    timestamp=entry.timestamp.astimezone(UTC),
                    run_id=entry.run_id,
                    direction=SignalDirection(entry.decision),
                    strength=SignalStrength.NONE,
                    raw_score=float(entry.scores.get("raw_score", 0.0)),
                    confidence=entry.confidence,
                    reasons=[SignalReason.model_validate(reason) for reason in entry.reasons if isinstance(reason, dict)],
                    regime=regime,
                    horizon=str(entry.raw_inputs.get("horizon", "unknown")),
                    entry_price=entry.raw_inputs.get("entry_price") if isinstance(entry.raw_inputs.get("entry_price"), float) else None,
                )
            )
        return results

    def _apply_filters(
        self,
        *,
        signal: Signal,
        asset_class: AssetClass,
        bars: list[OHLCVBar],
    ) -> tuple[bool, list[str], float, list[str]]:
        blocked: list[str] = []
        passed: list[str] = []
        multiplier = 1.0

        if self._config.filters.regime_filter:
            result = self._regime_filter.apply(signal)
            if not result.passed:
                blocked.append(result.reason or "regime_filter")
            else:
                passed.append("regime_filter")
                multiplier *= result.confidence_multiplier

        if self._config.filters.news_filter and not blocked:
            result = self._news_filter.apply(signal, asset_class)
            if not result.passed:
                blocked.append(result.reason or "news_filter")
            else:
                passed.append("news_filter")

        if self._config.filters.session_filter and not blocked:
            result = self._session_filter.apply(signal)
            if not result.passed:
                blocked.append(result.reason or "session_filter")
            else:
                passed.append("session_filter")

        if self._config.filters.spread_filter and not blocked:
            current_spread = bars[-1].spread
            spreads = [bar.spread for bar in bars[-30:] if bar.spread is not None and bar.spread > 0]
            avg_spread = sum(spreads) / len(spreads) if spreads else None
            result = self._spread_filter.apply(signal, current_spread=current_spread, average_spread=avg_spread)
            if not result.passed:
                blocked.append(result.reason or "spread_filter")
            else:
                passed.append("spread_filter")

        if self._config.filters.correlation_filter and not blocked:
            result = self._corr_filter.apply(signal)
            if not result.passed:
                blocked.append(result.reason or "correlation_filter")
            else:
                passed.append("correlation_filter")

        if blocked:
            return False, blocked, 1.0, passed
        return True, blocked, multiplier, passed

    async def _register_and_emit(self, decision: DecisionResult, timeframe_seconds: int) -> None:
        signal = self._final_signal_from_decision(decision)
        anti = self._anti.evaluate(signal, timeframe_seconds)
        if not anti.allowed:
            decision.ensemble.final_direction = SignalDirection.NO_TRADE
            decision.ensemble.filters_blocked.append(anti.reason or "anti_overtrading")
            decision.ensemble.explanation = self._explainer.explain_no_trade(anti.reason or "anti_overtrading")
            decision.display_decision = "NO OPERAR"
            decision.display_color = "gray"
            decision.display_emoji = "⛔"
            decision.confidence_percent = min(decision.confidence_percent, 30)
            return

        async with self._lock:
            self._anti.register_signal(signal)
            self._corr_filter.register(signal)
            self._active_signals.append(signal)
            self._signal_history.append(signal)

        await self._event_bus.publish(
            SignalEvent(
                source="signals.engine",
                run_id=self._run_id,
                symbol=signal.symbol,
                broker=signal.broker,
                strategy_id="signal_ensemble",
                strategy_version="1.0.0",
                direction=signal.direction.value,
                confidence=signal.confidence,
                reasons=[reason.model_dump(mode="python") for reason in signal.reasons],
                timeframe=signal.timeframe,
                horizon=signal.horizon,
                timestamp=signal.timestamp,
            )
        )

        await self._journal.write(
            JournalEntry(
                entry_id=signal.signal_id,
                timestamp=signal.timestamp,
                run_id=self._run_id,
                strategy_id="signal_ensemble",
                strategy_version="1.0.0",
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                raw_inputs={
                    "broker": signal.broker,
                    "horizon": signal.horizon,
                    "entry_price": signal.entry_price,
                },
                features={"top_reasons": [item.factor for item in signal.reasons[:5]]},
                scores={
                    "raw_score": signal.raw_score,
                    "agreement_score": decision.ensemble.agreement_score,
                    "regime": decision.ensemble.regime.model_dump(mode="python"),
                },
                decision=signal.direction.value,
                confidence=signal.confidence,
                reasons=[reason.model_dump(mode="python") for reason in signal.reasons],
                triggered_rule="signal_ensemble",
                triggered_condition="pipeline",
            )
        )

        self._logger.info(
            "signal_decision",
            symbol=decision.ensemble.symbol,
            timeframe=decision.ensemble.timeframe,
            direction=decision.display_decision,
            confidence=decision.confidence_percent,
        )

    def _to_decision(self, *, ensemble: EnsembleResult, asset_class: AssetClass) -> DecisionResult:
        direction = ensemble.final_direction
        if direction == SignalDirection.BUY:
            display_decision = "COMPRAR"
            color = "green"
            emoji = "🟢"
        elif direction == SignalDirection.SELL:
            display_decision = "VENDER"
            color = "red"
            emoji = "🔴"
        elif direction == SignalDirection.NO_TRADE:
            display_decision = "NO OPERAR"
            color = "gray"
            emoji = "⛔"
        else:
            display_decision = "NO HAY INFO CLARA"
            color = "yellow"
            emoji = "🟡"

        pct, _strength = self._confidence_scorer.get_display_confidence(ensemble.final_confidence)
        now = datetime.now(UTC)
        valid_until = now + timedelta(minutes=self._config.engine.signal_expiry_minutes)
        return DecisionResult(
            ensemble=ensemble,
            display_decision=display_decision,
            display_color=color,
            display_emoji=emoji,
            confidence_percent=pct,
            top_reasons=ensemble.all_reasons[:5],
            computed_at=now,
            valid_until=valid_until,
            asset_class=asset_class,
            horizon_human=self._explainer.horizon_to_human(ensemble.horizon),
        )

    def _final_signal_from_decision(self, decision: DecisionResult) -> Signal:
        ensemble = decision.ensemble
        return Signal(
            strategy_id="signal_ensemble",
            strategy_version="1.0.0",
            symbol=ensemble.symbol,
            broker=ensemble.broker,
            timeframe=ensemble.timeframe,
            timestamp=decision.computed_at,
            run_id=self._run_id,
            direction=ensemble.final_direction,
            strength=ensemble.final_strength,
            raw_score=(ensemble.final_confidence * 100.0) * (1 if ensemble.final_direction == SignalDirection.BUY else -1 if ensemble.final_direction == SignalDirection.SELL else 0),
            confidence=ensemble.final_confidence,
            reasons=ensemble.all_reasons[:10],
            regime=ensemble.regime,
            horizon=ensemble.horizon,
            entry_price=ensemble.contributing_signals[0].entry_price if ensemble.contributing_signals else None,
            expires_at=decision.valid_until,
            signal_id=str(uuid4()),
        )

    @staticmethod
    def _default_regime(*, symbol: str, timeframe: str, timestamp: datetime) -> MarketRegime:
        return MarketRegime(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp.astimezone(UTC),
            trend=TrendRegime.RANGING,
            volatility=VolatilityRegime.MEDIUM,
            liquidity=LiquidityRegime.LIQUID,
            is_tradeable=True,
            no_trade_reasons=[],
            confidence=0.5,
            recommended_strategies=["mean_reversion", "range_scalp"],
            description="fallback_regime",
            metrics={},
        )
