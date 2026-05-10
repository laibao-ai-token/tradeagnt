"""SuperTrend (ATR-based band trend)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator


def _wilder_rma(series: pd.Series, length: int) -> pd.Series:
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


@indicator(name="super_trend", category="trend", inputs=["high", "low", "close"])
def super_trend(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = _wilder_rma(tr, length)
    hl2 = (df["high"] + df["low"]) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    # Trend following logic
    trend = np.zeros(len(df))
    for i in range(1, len(df)):
        if df["close"].iloc[i] > upper.iloc[i - 1]:
            trend[i] = 1
        elif df["close"].iloc[i] < lower.iloc[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
            if trend[i] == 1 and df["close"].iloc[i] < lower.iloc[i - 1]:
                trend[i] = -1
            elif trend[i] == -1 and df["close"].iloc[i] > upper.iloc[i - 1]:
                trend[i] = 1
    df["super_trend_upper"] = upper
    df["super_trend_lower"] = lower
    df["super_trend_direction"] = np.where(trend == 1, "up", np.where(trend == -1, "down", "neutral"))
    return df
