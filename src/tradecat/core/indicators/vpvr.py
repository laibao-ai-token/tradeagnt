"""Volume Profile Visible Range (simplified)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradecat.core.indicators.base import indicator


@indicator(name="vpvr", category="volume", inputs=["high", "low", "close", "volume"])
def vpvr(df: pd.DataFrame, num_bins: int = 48, value_area_pct: float = 0.7) -> pd.DataFrame:
    price_min = float(df["low"].min())
    price_max = float(df["high"].max())
    if price_max <= price_min:
        price_max = price_min + 1e-6
    bin_edges = np.linspace(price_min, price_max, num_bins + 1)
    df["vpvr_bin"] = pd.cut(df["close"], bins=bin_edges, labels=False)
    vol_by_bin = df.groupby("vpvr_bin")["volume"].sum().sort_values(ascending=False)
    if len(vol_by_bin) == 0:
        df["vpvr_poc"] = np.nan
        df["vpvr_va_high"] = np.nan
        df["vpvr_va_low"] = np.nan
        return df
    poc_bin = int(vol_by_bin.idxmax())
    poc_price = (bin_edges[poc_bin] + bin_edges[poc_bin + 1]) / 2
    # Value area: accumulate from POC outward until volume >= value_area_pct of total
    total_vol = float(df["volume"].sum())
    target_vol = total_vol * value_area_pct
    bins_sorted = vol_by_bin.index.tolist()
    poc_idx = bins_sorted.index(poc_bin)
    accumulated = float(vol_by_bin.iloc[poc_idx])
    left = right = poc_idx
    while accumulated < target_vol and (left > 0 or right < len(bins_sorted) - 1):
        l_vol = vol_by_bin.iloc[left - 1] if left > 0 else -1
        r_vol = vol_by_bin.iloc[right + 1] if right < len(bins_sorted) - 1 else -1
        if l_vol >= r_vol and left > 0:
            left -= 1
            accumulated += float(vol_by_bin.iloc[left])
        elif right < len(bins_sorted) - 1:
            right += 1
            accumulated += float(vol_by_bin.iloc[right])
        else:
            break
    va_low = float(bin_edges[int(bins_sorted[left])])
    va_high = float(bin_edges[int(bins_sorted[right]) + 1])
    df["vpvr_poc"] = poc_price
    df["vpvr_va_high"] = va_high
    df["vpvr_va_low"] = va_low
    return df
