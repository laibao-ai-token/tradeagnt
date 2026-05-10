"""Volume ratio vs rolling average."""
from __future__ import annotations

import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="volume_ratio", category="volume", inputs=["volume"])
def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    avg = df["volume"].rolling(window=period, min_periods=period).mean()
    df["volume_ratio"] = df["volume"] / avg.replace(0, np.nan)
    return df
