"""On-Balance Volume."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="obv", category="volume", inputs=["close", "volume"])
def obv(df: pd.DataFrame) -> pd.DataFrame:
    direction = np.sign(df["close"].diff()).fillna(0)
    df["obv"] = (direction * df["volume"]).cumsum()
    return df
