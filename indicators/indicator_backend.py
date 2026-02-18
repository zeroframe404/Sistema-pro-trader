"""Indicator backend abstraction with graceful fallback."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class IndicatorBackend:
    """Expose a normalized indicator API regardless of backing library."""

    def __init__(self, preference: str = "auto") -> None:
        self._talib: Any = None
        self._pandas_ta: Any = None
        self._ta: Any = None

        self._talib_available = self._check_talib()
        self._pandas_ta_available = self._check_pandas_ta()
        self._ta_available = self._check_ta()
        self._backend = self._select_backend(preference)

    @property
    def backend_name(self) -> str:
        return self._backend

    def _check_talib(self) -> bool:
        try:
            import talib  # type: ignore[import-not-found]

            self._talib = talib
            return True
        except Exception:
            return False

    def _check_pandas_ta(self) -> bool:
        try:
            import pandas_ta as pandas_ta  # type: ignore[import-not-found]

            self._pandas_ta = pandas_ta
            return True
        except Exception:
            return False

    def _check_ta(self) -> bool:
        try:
            import ta  # type: ignore[import-not-found]

            self._ta = ta
            return True
        except Exception:
            return False

    def _select_backend(self, preference: str) -> str:
        pref = preference.lower()
        if pref == "talib" and self._talib_available:
            return "talib"
        if pref in {"pandas_ta", "pandas-ta"} and self._pandas_ta_available:
            return "pandas_ta"
        if pref == "ta" and self._ta_available:
            return "ta"
        if pref == "custom":
            return "custom"

        if self._talib_available:
            return "talib"
        if self._pandas_ta_available:
            return "pandas_ta"
        if self._ta_available:
            return "ta"
        return "custom"

    def sma(self, close: np.ndarray, period: int) -> np.ndarray:
        if period <= 0:
            raise ValueError("period must be > 0")

        if self._backend == "talib":
            result = self._talib.SMA(close, timeperiod=period)
            return np.asarray(result, dtype=float)

        series = pd.Series(close, dtype=float)
        return np.asarray(series.rolling(window=period, min_periods=period).mean().to_numpy(dtype=float), dtype=float)

    def ema(self, close: np.ndarray, period: int) -> np.ndarray:
        if period <= 0:
            raise ValueError("period must be > 0")

        if self._backend == "talib":
            result = self._talib.EMA(close, timeperiod=period)
            return np.asarray(result, dtype=float)

        series = pd.Series(close, dtype=float)
        return np.asarray(series.ewm(span=period, adjust=False).mean().to_numpy(dtype=float), dtype=float)

    def rsi(self, close: np.ndarray, period: int) -> np.ndarray:
        if period <= 0:
            raise ValueError("period must be > 0")

        if self._backend == "talib":
            result = self._talib.RSI(close, timeperiod=period)
            return np.asarray(result, dtype=float)

        if self._backend == "pandas_ta":
            series = pd.Series(close, dtype=float)
            result = self._pandas_ta.rsi(series, length=period)
            return np.asarray(result.to_numpy(dtype=float), dtype=float)

        series = pd.Series(close, dtype=float)
        delta = series.diff()
        up = delta.clip(lower=0)
        down = -delta.clip(upper=0)
        avg_gain = up.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = down.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        out = 100.0 - (100.0 / (1.0 + rs))
        flat_mask = (avg_gain == 0) & (avg_loss == 0)
        out = out.mask(flat_mask, 50.0)
        return np.asarray(out.to_numpy(dtype=float), dtype=float)

    def macd(
        self,
        close: np.ndarray,
        fast: int,
        slow: int,
        signal: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._backend == "talib":
            macd, macd_signal, macd_hist = self._talib.MACD(
                close,
                fastperiod=fast,
                slowperiod=slow,
                signalperiod=signal,
            )
            return (
                np.asarray(macd, dtype=float),
                np.asarray(macd_signal, dtype=float),
                np.asarray(macd_hist, dtype=float),
            )

        ema_fast = self.ema(close, fast)
        ema_slow = self.ema(close, slow)
        macd_line = ema_fast - ema_slow
        signal_line = self.ema(macd_line, signal)
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    def atr(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        period: int,
    ) -> np.ndarray:
        if self._backend == "talib":
            result = self._talib.ATR(high, low, close, timeperiod=period)
            return np.asarray(result, dtype=float)

        high_s = pd.Series(high, dtype=float)
        low_s = pd.Series(low, dtype=float)
        close_s = pd.Series(close, dtype=float)
        prev_close = close_s.shift(1)
        tr = pd.concat(
            [
                (high_s - low_s),
                (high_s - prev_close).abs(),
                (low_s - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        return np.asarray(atr.to_numpy(dtype=float), dtype=float)

    def bbands(
        self,
        close: np.ndarray,
        period: int,
        std_dev: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._backend == "talib":
            upper, middle, lower = self._talib.BBANDS(
                close,
                timeperiod=period,
                nbdevup=std_dev,
                nbdevdn=std_dev,
            )
            return (
                np.asarray(upper, dtype=float),
                np.asarray(middle, dtype=float),
                np.asarray(lower, dtype=float),
            )

        series = pd.Series(close, dtype=float)
        middle_s = series.rolling(window=period, min_periods=period).mean()
        std_s = series.rolling(window=period, min_periods=period).std(ddof=0)
        upper_s = middle_s + (std_s * std_dev)
        lower_s = middle_s - (std_s * std_dev)
        return (
            upper_s.to_numpy(dtype=float),
            middle_s.to_numpy(dtype=float),
            lower_s.to_numpy(dtype=float),
        )

    def stoch(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        k_period: int,
        d_period: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        if self._backend == "talib":
            k, d = self._talib.STOCH(
                high,
                low,
                close,
                fastk_period=k_period,
                slowk_period=d_period,
                slowd_period=d_period,
            )
            return np.asarray(k, dtype=float), np.asarray(d, dtype=float)

        high_s = pd.Series(high, dtype=float)
        low_s = pd.Series(low, dtype=float)
        close_s = pd.Series(close, dtype=float)
        lowest = low_s.rolling(window=k_period, min_periods=k_period).min()
        highest = high_s.rolling(window=k_period, min_periods=k_period).max()
        denom = (highest - lowest).replace(0, np.nan)
        k = 100.0 * ((close_s - lowest) / denom)
        d = k.rolling(window=d_period, min_periods=d_period).mean()
        return np.asarray(k.to_numpy(dtype=float), dtype=float), np.asarray(d.to_numpy(dtype=float), dtype=float)

    def adx(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        period: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._backend == "talib":
            adx = self._talib.ADX(high, low, close, timeperiod=period)
            plus = self._talib.PLUS_DI(high, low, close, timeperiod=period)
            minus = self._talib.MINUS_DI(high, low, close, timeperiod=period)
            return (
                np.asarray(adx, dtype=float),
                np.asarray(plus, dtype=float),
                np.asarray(minus, dtype=float),
            )

        high_s = pd.Series(high, dtype=float)
        low_s = pd.Series(low, dtype=float)
        close_s = pd.Series(close, dtype=float)

        up_move = high_s.diff()
        down_move = -low_s.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        prev_close = close_s.shift(1)
        tr = pd.concat(
            [
                high_s - low_s,
                (high_s - prev_close).abs(),
                (low_s - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        plus_di = 100.0 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)
        minus_di = 100.0 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)

        denom = (plus_di + minus_di).replace(0, np.nan)
        dx = 100.0 * (plus_di - minus_di).abs() / denom
        adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        return (
            adx.to_numpy(dtype=float),
            plus_di.to_numpy(dtype=float),
            minus_di.to_numpy(dtype=float),
        )
