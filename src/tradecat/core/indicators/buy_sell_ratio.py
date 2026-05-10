"""Buy/Sell volume ratio."""
from __future__ import annotations

import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="buy_sell_ratio", category="volume", inputs=["volume", "taker_buy_volume"])
def buy_sell_ratio(df: pd.DataFrame) -> pd.DataFrame:
    if "taker_buy_volume" in df.columns:
        buy = df["taker_buy_volume"].astype(float).fillna(0)
    else:
        buy = df["volume"] * 0.5
    sell = (df["volume"].astype(float) - buy).clip(lower=0)
    total = buy + sell
    df["buy_sell_ratio"] = buy / total.where(total > 0, 1)
    return df
