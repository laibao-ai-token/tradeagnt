"""Support & Resistance levels from recent window extrema."""
from __future__ import annotations

import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="support_resistance", category="price_levels", inputs=["high", "low"])
def support_resistance(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    df["sr_support"] = df["low"].rolling(window=window, min_periods=window).min()
    df["sr_resistance"] = df["high"].rolling(window=window, min_periods=window).max()
    return df
