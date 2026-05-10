"""EMA alignment (simplified from ema_gc)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="ema", category="trend", inputs=["close"])
def ema(df: pd.DataFrame, fast: int = 7, medium: int = 25, slow: int = 99) -> pd.DataFrame:
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_medium"] = df["close"].ewm(span=medium, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    ef, em, es = df["ema_fast"], df["ema_medium"], df["ema_slow"]
    df["ema_trend"] = np.where(
        (ef > em) & (em > es), "bullish",
        np.where((ef < em) & (em < es), "bearish", "neutral")
    )
    return df
