"""Cumulative Volume Delta."""
from __future__ import annotations

import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="cvd", category="volume", inputs=["volume", "taker_buy_volume"])
def cvd(df: pd.DataFrame) -> pd.DataFrame:
    if "taker_buy_volume" in df.columns:
        buy = df["taker_buy_volume"].astype(float).fillna(0)
    else:
        buy = df["volume"] * 0.5
    sell = (df["volume"].astype(float) - buy).clip(lower=0)
    delta = buy - sell
    df["cvd"] = delta.cumsum()
    return df
