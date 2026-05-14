"""Gate.io data provider (via httpx REST API, bypasses ccxt market loading)."""
from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from tradecat.core.providers.base import DataProvider


class GateProvider(DataProvider):
    """Gate.io spot market data provider using direct REST API."""

    _INTERVALS = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "4h": "4h", "8h": "8h", "1d": "1d",
        "7d": "7d", "30d": "30d",
    }

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=15)

    @property
    def name(self) -> str:
        return "gate"

    async def fetch_klines(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> pd.DataFrame:
        pair = symbol.upper().replace("/", "_")  # BTCUSDT -> BTC_USDT, BTC/USDT -> BTC_USDT
        if "_" not in pair:
            pair = pair.replace("USDT", "_USDT")
        interval = self._INTERVALS.get(timeframe, timeframe)
        resp = await self._client.get(
            "https://api.gateio.ws/api/v4/spot/candlesticks",
            params={"currency_pair": pair, "interval": interval, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
        # Gate.io format: [timestamp, quote_vol, close, high, low, open, base_vol, is_window_closed]
        rows = []
        for d in data:
            rows.append({
                "timestamp": pd.to_datetime(int(d[0]), unit="s", utc=True),
                "open": float(d[5]),
                "high": float(d[3]),
                "low": float(d[4]),
                "close": float(d[2]),
                "volume": float(d[6]),
            })
        df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
        return df

    async def fetch_latest(self, symbol: str) -> dict[str, Any]:
        pair = symbol.upper().replace("/", "_")
        if "_" not in pair:
            pair = pair.replace("USDT", "_USDT")
        resp = await self._client.get(
            "https://api.gateio.ws/api/v4/spot/tickers",
            params={"currency_pair": pair},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ValueError(f"No ticker data for {symbol}")
        t = data[0]
        return {
            "symbol": symbol,
            "price": float(t["last"]),
            "volume_24h": float(t.get("quote_volume", 0)),
        }

    def supported_symbols(self) -> list[str]:
        return [
            "BTC_USDT", "ETH_USDT", "SOL_USDT", "GT_USDT", "XRP_USDT",
        ]

    def can_resolve(self, symbol: str) -> bool:
        s = symbol.upper()
        return s.endswith("USDT") or "_USDT" in s

    async def close(self) -> None:
        await self._client.aclose()
