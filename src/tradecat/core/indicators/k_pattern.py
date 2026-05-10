"""Candlestick pattern detection (basic, no talib)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="k_pattern", category="pattern", inputs=["open", "high", "low", "close"])
def k_pattern(df: pd.DataFrame) -> pd.DataFrame:
    body = (df["close"] - df["open"]).abs()
    upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)
    lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]
    total_range = df["high"] - df["low"]

    # Doji: body is tiny relative to range; treat high==low as doji
    df["k_doji"] = (body / total_range.replace(0, np.nan) < 0.1).fillna(True)
    df["k_hammer"] = (lower_shadow > body * 2) & (upper_shadow < body * 0.5) & (df["close"] > df["open"])
    df["k_shooting_star"] = (upper_shadow > body * 2) & (lower_shadow < body * 0.5) & (df["close"] < df["open"])
    prev_open = df["open"].shift(1)
    prev_close = df["close"].shift(1)
    df["k_engulfing_bull"] = (df["close"] > df["open"]) & (prev_close < prev_open) &                              (df["open"] < prev_close) & (df["close"] > prev_open)
    df["k_engulfing_bear"] = (df["close"] < df["open"]) & (prev_close > prev_open) &                              (df["open"] > prev_close) & (df["close"] < prev_open)
    return df
