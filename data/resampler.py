"""Timeframe conversion and aggregation helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from data.models import OHLCVBar, Tick


class Resampler:
    """Resample ticks/bars between supported timeframes."""

    def ticks_to_ohlcv(
        self,
        ticks: list[Tick],
        timeframe: str,
        price_field: str = "last",
    ) -> list[OHLCVBar]:
        """Aggregate ticks into OHLCV bars without generating empty periods."""

        if not ticks:
            return []

        tf_seconds = self.get_timeframe_seconds(timeframe)
        ordered = sorted(ticks, key=lambda item: item.timestamp)
        grouped: dict[datetime, list[Tick]] = {}

        for tick in ordered:
            timestamp_utc = tick.timestamp.astimezone(UTC)
            bucket_start = datetime.fromtimestamp(
                int(timestamp_utc.timestamp() // tf_seconds) * tf_seconds,
                tz=UTC,
            )
            grouped.setdefault(bucket_start, []).append(tick)

        bars: list[OHLCVBar] = []
        for bucket_start in sorted(grouped):
            bucket_ticks = grouped[bucket_start]
            prices = [self._select_price(item, price_field) for item in bucket_ticks]

            open_price = prices[0]
            close_price = prices[-1]
            high_price = max(prices)
            low_price = min(prices)
            volume = sum((item.volume or 0.0) for item in bucket_ticks)
            spread_values = [item.spread for item in bucket_ticks if item.spread is not None]
            spread = sum(spread_values) / len(spread_values) if spread_values else None

            first_tick = bucket_ticks[0]
            bars.append(
                OHLCVBar(
                    symbol=first_tick.symbol,
                    broker=first_tick.broker,
                    timeframe=timeframe,
                    timestamp_open=bucket_start,
                    timestamp_close=bucket_start + timedelta(seconds=tf_seconds),
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                    tick_count=len(bucket_ticks),
                    spread=spread,
                    asset_class=first_tick.asset_class,
                    source=first_tick.source,
                )
            )

        return bars

    def resample_ohlcv(
        self,
        bars: list[OHLCVBar],
        source_timeframe: str,
        target_timeframe: str,
    ) -> list[OHLCVBar]:
        """Upsample a bar series from source timeframe to target timeframe."""

        if not bars:
            return []

        source_seconds = self.get_timeframe_seconds(source_timeframe)
        target_seconds = self.get_timeframe_seconds(target_timeframe)

        if target_seconds <= source_seconds:
            raise ValueError("downsampling is not allowed")
        if target_seconds % source_seconds != 0:
            raise ValueError("target timeframe must be an exact multiple of source timeframe")

        ordered = sorted(bars, key=lambda item: item.timestamp_open)
        grouped: dict[datetime, list[OHLCVBar]] = {}

        for bar in ordered:
            open_ts = bar.timestamp_open.astimezone(UTC)
            bucket_start = datetime.fromtimestamp(
                int(open_ts.timestamp() // target_seconds) * target_seconds,
                tz=UTC,
            )
            grouped.setdefault(bucket_start, []).append(bar)

        result: list[OHLCVBar] = []
        for bucket_start in sorted(grouped):
            bucket = grouped[bucket_start]
            first = bucket[0]
            result.append(
                OHLCVBar(
                    symbol=first.symbol,
                    broker=first.broker,
                    timeframe=target_timeframe,
                    timestamp_open=bucket_start,
                    timestamp_close=bucket_start + timedelta(seconds=target_seconds),
                    open=bucket[0].open,
                    high=max(item.high for item in bucket),
                    low=min(item.low for item in bucket),
                    close=bucket[-1].close,
                    volume=sum(item.volume for item in bucket),
                    tick_count=sum(item.tick_count or 0 for item in bucket) or None,
                    spread=(sum(item.spread for item in bucket if item.spread is not None) / max(1, sum(1 for item in bucket if item.spread is not None))) if any(item.spread is not None for item in bucket) else None,
                    asset_class=first.asset_class,
                    source=first.source,
                )
            )

        return result

    def get_timeframe_seconds(self, timeframe: str) -> int:
        """Return timeframe duration in seconds."""

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
        tf = timeframe.upper()
        if tf not in mapping:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        return mapping[tf]

    def is_bar_complete(self, bar_open_time: datetime, timeframe: str) -> bool:
        """Return True if the bar close time has passed in UTC."""

        open_utc = bar_open_time.astimezone(UTC) if bar_open_time.tzinfo is not None else bar_open_time.replace(tzinfo=UTC)
        close_time = open_utc + timedelta(seconds=self.get_timeframe_seconds(timeframe))
        return datetime.now(UTC) >= close_time

    @staticmethod
    def _select_price(tick: Tick, field: str) -> float:
        if field == "bid":
            return tick.bid
        if field == "ask":
            return tick.ask
        if field == "mid":
            return (tick.bid + tick.ask) / 2

        if tick.last is not None:
            return tick.last
        return (tick.bid + tick.ask) / 2
