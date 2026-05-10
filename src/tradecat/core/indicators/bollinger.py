"""Bollinger Bands."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="bollinger", category="volatility", inputs=["close"])
def bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    ma = df["close"].rolling(window=period, min_periods=period).mean()
    std = df["close"].rolling(window=period, min_periods=period).std()
    df["bb_upper"] = ma + std_dev * std
    df["bb_middle"] = ma
    df["bb_lower"] = ma - std_dev * std
    df["bb_width_pct"] = (df["bb_upper"] - df["bb_lower"]) / ma.replace(0, np.nan) * 100
    return df
