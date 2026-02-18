"""OHLCV and tick quality validation utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import mean, pstdev

from data.models import DataQualityReport, OHLCVBar, Tick


class DataValidator:
    """Validate and repair data series quality."""

    def __init__(self, outlier_std_threshold: float = 4.0) -> None:
        self._outlier_std_threshold = outlier_std_threshold

    def validate_series(
        self,
        bars: list[OHLCVBar],
        expected_timeframe: str,
        allow_gaps_in: list[str] | None = None,
    ) -> DataQualityReport:
        """Validate bar quality and return a detailed report."""

        allow_gaps_in = allow_gaps_in or []
        if not bars:
            now = datetime.now(UTC)
            return DataQualityReport(
                symbol="UNKNOWN",
                broker="UNKNOWN",
                timeframe=expected_timeframe,
                period_start=now,
                period_end=now,
                total_bars=0,
                missing_bars=0,
                duplicate_bars=0,
                corrupt_bars=0,
                outlier_bars=0,
                timezone_issues=0,
                gap_details=[],
                quality_score=0.0,
                is_usable=False,
            )

        sorted_bars = sorted(bars, key=lambda item: item.timestamp_open)
        total_bars = len(sorted_bars)
        timeframe_seconds = self._timeframe_seconds(expected_timeframe)

        duplicate_bars = 0
        corrupt_bars = 0
        timezone_issues = 0
        outlier_bars = 0
        missing_bars = 0
        gap_details: list[dict[str, object]] = []

        seen_opens: set[datetime] = set()
        closes = [bar.close for bar in sorted_bars]
        close_avg = mean(closes)
        close_std = pstdev(closes) if len(closes) > 1 else 0.0

        for index, bar in enumerate(sorted_bars):
            if bar.timestamp_open.tzinfo is None or bar.timestamp_close.tzinfo is None:
                timezone_issues += 1

            if bar.timestamp_open in seen_opens:
                duplicate_bars += 1
            seen_opens.add(bar.timestamp_open)

            if (
                bar.high < bar.low
                or bar.high < max(bar.open, bar.close)
                or bar.low > min(bar.open, bar.close)
                or bar.open <= 0
                or bar.close <= 0
            ):
                corrupt_bars += 1

            if close_std > 0 and abs(bar.close - close_avg) > self._outlier_std_threshold * close_std:
                outlier_bars += 1

            if index == 0:
                continue

            previous = sorted_bars[index - 1]
            delta_seconds = int((bar.timestamp_open - previous.timestamp_open).total_seconds())
            if delta_seconds <= 0:
                corrupt_bars += 1
                continue

            if delta_seconds > timeframe_seconds:
                gap_count = (delta_seconds // timeframe_seconds) - 1
                if gap_count > 0:
                    missing_bars += gap_count
                    gap_details.append(
                        {
                            "from": previous.timestamp_open.isoformat(),
                            "to": bar.timestamp_open.isoformat(),
                            "missing_bars": gap_count,
                        }
                    )

        penalty = missing_bars + duplicate_bars + corrupt_bars + outlier_bars + timezone_issues
        denominator = max(total_bars, 1)
        quality_score = max(0.0, 1.0 - (penalty / denominator))

        first = sorted_bars[0]
        return DataQualityReport(
            symbol=first.symbol,
            broker=first.broker,
            timeframe=expected_timeframe,
            period_start=sorted_bars[0].timestamp_open,
            period_end=sorted_bars[-1].timestamp_close,
            total_bars=total_bars,
            missing_bars=missing_bars,
            duplicate_bars=duplicate_bars,
            corrupt_bars=corrupt_bars,
            outlier_bars=outlier_bars,
            timezone_issues=timezone_issues,
            gap_details=gap_details,
            quality_score=quality_score,
            is_usable=quality_score >= 0.8,
        )

    def fix_series(self, bars: list[OHLCVBar], strategy: str = "drop") -> list[OHLCVBar]:
        """Attempt to repair a series with the selected strategy."""

        if strategy not in {"drop", "forward_fill", "interpolate"}:
            raise ValueError("strategy must be one of: drop, forward_fill, interpolate")

        ordered = sorted(bars, key=lambda item: item.timestamp_open)
        cleaned: list[OHLCVBar] = []

        for bar in ordered:
            is_corrupt = (
                bar.high < bar.low
                or bar.open <= 0
                or bar.close <= 0
                or bar.high < max(bar.open, bar.close)
                or bar.low > min(bar.open, bar.close)
            )
            if not is_corrupt:
                cleaned.append(bar)
                continue

            if strategy == "drop":
                continue

            if not cleaned:
                continue

            previous = cleaned[-1]
            if strategy == "forward_fill":
                cleaned.append(
                    bar.model_copy(
                        update={
                            "open": previous.close,
                            "high": previous.close,
                            "low": previous.close,
                            "close": previous.close,
                            "volume": 0.0,
                        }
                    )
                )
                continue

            # interpolate
            interpolated_close = (previous.close + bar.close) / 2 if bar.close > 0 else previous.close
            cleaned.append(
                bar.model_copy(
                    update={
                        "open": previous.close,
                        "high": max(previous.close, interpolated_close),
                        "low": min(previous.close, interpolated_close),
                        "close": interpolated_close,
                        "volume": max(bar.volume, 0.0),
                    }
                )
            )

        unique_by_open: dict[datetime, OHLCVBar] = {}
        for bar in cleaned:
            unique_by_open[bar.timestamp_open] = bar

        return sorted(unique_by_open.values(), key=lambda item: item.timestamp_open)

    def validate_tick(self, tick: Tick) -> bool:
        """Validate a single tick payload."""

        if tick.timestamp.tzinfo is None:
            return False
        if tick.bid <= 0 or tick.ask <= 0:
            return False
        if tick.bid > tick.ask:
            return False

        age = datetime.now(UTC) - tick.timestamp.astimezone(UTC)
        return age < timedelta(days=7)

    def detect_spread_spike(self, tick: Tick, history: list[Tick], threshold: float = 3.0) -> bool:
        """Return True when spread spikes compared to historical average."""

        spreads = [item.spread for item in history if item.spread is not None]
        if not spreads:
            return False

        avg_spread = mean(spreads)
        if avg_spread <= 0:
            return False

        current_spread = tick.spread if tick.spread is not None else tick.ask - tick.bid
        return current_spread > avg_spread * threshold

    @staticmethod
    def _timeframe_seconds(timeframe: str) -> int:
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
        return mapping.get(timeframe.upper(), 60)
