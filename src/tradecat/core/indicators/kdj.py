"""KDJ stochastic indicator."""
from __future__ import annotations

import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="kdj", category="momentum", inputs=["high", "low", "close"])
def kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    low_n = df["low"].rolling(window=n, min_periods=n).min()
    high_n = df["high"].rolling(window=n, min_periods=n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n) * 100
    k = rsv.ewm(alpha=1/m1, adjust=False, min_periods=m1).mean()
    d = k.ewm(alpha=1/m2, adjust=False, min_periods=m2).mean()
    j = 3 * k - 2 * d
    df["kdj_k"] = k
    df["kdj_d"] = d
    df["kdj_j"] = j
    return df
