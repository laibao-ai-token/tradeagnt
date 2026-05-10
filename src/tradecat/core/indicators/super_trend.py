"""SuperTrend (Zero-Lag EMA based, faithful to original)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator

DEFAULT_LENGTH = 70
DEFAULT_MULT = 1.2


def _rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder RMA (smoothed moving average)."""
    alpha = 1.0 / length
    vals = []
    prev = np.nan
    for i, v in enumerate(series):
        if i == 0 or not np.isfinite(prev):
            prev = v if np.isfinite(v) else 0.0
        else:
            prev = alpha * v + (1 - alpha) * prev
        vals.append(prev)
    return pd.Series(vals, index=series.index)


def _atr_wilder(df: pd.DataFrame, length: int = DEFAULT_LENGTH) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return _rma(tr, length)


def _zlema(close: pd.Series, length: int = DEFAULT_LENGTH, lag: int | None = None) -> pd.Series:
    """Zero-lag EMA: EMA(close + (close - close[lag]))."""
    if lag is None:
        lag = (length - 1) // 2
    src = close + (close - close.shift(lag))
    return src.ewm(span=length, adjust=False).mean()


@indicator(name="super_trend", category="trend", inputs=["high", "low", "close"])
def super_trend(
    df: pd.DataFrame,
    length: int = DEFAULT_LENGTH,
    mult: float = DEFAULT_MULT,
) -> pd.DataFrame:
    """Original SuperTrend: ZLEMA baseline + highest(ATR, length*3) * multiplier."""
    lag = (length - 1) // 2
    highest_win = length * 3

    close = df["close"]
    zlema = _zlema(close, length, lag)
    atr = _atr_wilder(df, length)
    vol_band = atr.rolling(highest_win, min_periods=1).max() * mult

    trend = np.zeros(len(close))
    for i in range(1, len(close)):
        upper = zlema.iloc[i] + vol_band.iloc[i]
        lower = zlema.iloc[i] - vol_band.iloc[i]
        if close.iloc[i - 1] <= upper and close.iloc[i] > upper:
            trend[i] = 1
        elif close.iloc[i - 1] >= lower and close.iloc[i] < lower:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]

    df["super_trend_zlema"] = zlema
    df["super_trend_upper"] = zlema + vol_band
    df["super_trend_lower"] = zlema - vol_band
    df["super_trend_direction"] = np.where(
        trend == 1, "up",
        np.where(trend == -1, "down", "neutral"),
    )
    df["super_trend_band"] = np.where(
        trend == 1, df["super_trend_lower"], df["super_trend_upper"],
    )
    return df
