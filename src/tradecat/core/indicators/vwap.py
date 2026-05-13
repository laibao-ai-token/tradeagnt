"""Volume Weighted Average Price."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="vwap", category="volume", inputs=["high", "low", "close", "volume"])
def vwap(df: pd.DataFrame) -> pd.DataFrame:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (tp * df["volume"]).cumsum()
    df["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)
    return df
