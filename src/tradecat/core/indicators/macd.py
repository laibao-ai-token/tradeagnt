"""MACD indicator."""
from __future__ import annotations

import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="macd", category="momentum", inputs=["close"])
def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = 2 * (dif - dea)
    df["macd_dif"] = dif
    df["macd_dea"] = dea
    df["macd_hist"] = hist
    return df
