"""Futures sentiment (funding rate / OI driven)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="futures_sentiment", category="sentiment", inputs=["close"])
def futures_sentiment(
    df: pd.DataFrame,
    funding_col: str = "funding_rate",
    oi_col: str = "open_interest",
) -> pd.DataFrame:
    if funding_col in df.columns and oi_col in df.columns:
        # Negative funding = longs pay shorts = bearish bias
        df["futures_sentiment"] = -df[funding_col] * 100
    else:
        df["futures_sentiment"] = np.nan
    return df
