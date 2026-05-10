"""Average True Range."""
from __future__ import annotations

import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="atr", category="volatility", inputs=["high", "low", "close"])
def atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    return df
