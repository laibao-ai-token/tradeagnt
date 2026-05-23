"""US equity data provider (Nasdaq / Tencent / Yahoo via core HTTP layer)."""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from tradecat.core.providers.base import DataProvider
from tradecat.core.symbols.equity import is_us_ticker, normalize_us_ticker

_TIMEFRAME_RULES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}


def _minute_series_to_df(
    series: list[tuple[int, float, float]],
) -> pd.DataFrame:
    if not series:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    rows = []
    prev_vol = 0.0
    for epoch_s, price, vol_cum in series:
        bar_vol = max(0.0, vol_cum - prev_vol) if vol_cum >= prev_vol else max(0.0, vol_cum)
        prev_vol = vol_cum
        rows.append(
            {
                "timestamp": pd.to_datetime(int(epoch_s), unit="s", utc=True),
                "open": float(price),
                "high": float(price),
                "low": float(price),
                "close": float(price),
                "volume": float(bar_vol),
            }
        )
    return pd.DataFrame(rows)


def _resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if df.empty:
        return df
    rule = _TIMEFRAME_RULES.get((timeframe or "5m").strip().lower(), "5min")
    if rule == "1min":
        return df.reset_index(drop=True)
    indexed = df.set_index("timestamp")
    resampled = indexed.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    resampled = resampled.dropna(subset=["close"])
    resampled = resampled.reset_index()
    return resampled


def _fetch_us_minute_series_sync(symbol: str, limit: int) -> list[tuple[int, float, float]]:
    from tradecat.core.providers.us_market_http import (
        fetch_nasdaq_us_minute_series,
        fetch_tencent_us_minute_series,
    )

    safe_limit = max(30, min(int(limit), 390))
    series = fetch_nasdaq_us_minute_series(symbol, timeout_s=8.0, limit=safe_limit)
    if series:
        return series
    return fetch_tencent_us_minute_series(symbol, timeout_s=8.0, limit=safe_limit)


class UsEquityProvider(DataProvider):
    """US stock market data (intraday 1m → resampled OHLCV)."""

    @property
    def name(self) -> str:
        return "us_equity"

    async def fetch_klines(
        self, symbol: str, timeframe: str = "5m", limit: int = 100
    ) -> pd.DataFrame:
        return await asyncio.to_thread(self._fetch_klines_sync, symbol, timeframe, limit)

    def _fetch_klines_sync(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        sym = normalize_us_ticker(symbol)
        if not sym:
            raise ValueError(f"Invalid US ticker: {symbol}")

        tf = (timeframe or "5m").strip().lower()
        tf_candles_per_day = {"1m": 390, "5m": 78, "15m": 26, "30m": 13, "1h": 7, "1d": 1}
        minute_need = max(limit * 5, tf_candles_per_day.get(tf, 78) * 3, 120)
        minute_need = min(minute_need, 390)

        series = _fetch_us_minute_series_sync(sym, minute_need)
        df = _minute_series_to_df(series)
        if df.empty:
            return df
        df = _resample_ohlcv(df, tf)
        if limit and len(df) > limit:
            df = df.tail(int(limit)).reset_index(drop=True)
        return df

    async def fetch_latest(self, symbol: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._fetch_latest_sync, symbol)

    def _fetch_latest_sync(self, symbol: str) -> dict[str, Any]:
        from tradecat.core.providers.us_market_http import fetch_tencent_us_quote, fetch_yahoo_us_stock_quote

        sym = normalize_us_ticker(symbol)
        if not sym:
            raise ValueError(f"Invalid US ticker: {symbol}")
        q = fetch_tencent_us_quote(sym, timeout_s=5.0)
        if q is None or q.price <= 0:
            q = fetch_yahoo_us_stock_quote(sym, timeout_s=6.0)
        if q is None or q.price <= 0:
            raise ValueError(f"No quote for {sym}")
        return {
            "symbol": sym,
            "price": float(q.price),
            "volume_24h": float(q.volume),
            "currency": q.currency or "USD",
            "source": q.source,
        }

    def supported_symbols(self) -> list[str]:
        return ["NVDA", "AAPL", "MSFT", "META", "TSLA", "AMD", "ORCL"]

    def can_resolve(self, symbol: str) -> bool:
        return is_us_ticker(symbol)

    async def close(self) -> None:
        pass
