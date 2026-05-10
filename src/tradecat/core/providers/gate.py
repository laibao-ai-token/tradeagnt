"""Gate.io data provider (via ccxt)."""
from __future__ import annotations

from typing import Any

import ccxt.async_support as ccxt
import pandas as pd

from tradecat.core.providers.base import DataProvider


class GateProvider(DataProvider):
    """Gate.io spot market data provider."""

    def __init__(self) -> None:
        self._exchange = ccxt.gateio({"options": {"defaultType": "spot"}})

    @property
    def name(self) -> str:
        return "gate"

    async def fetch_klines(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> pd.DataFrame:
        ohlcv = await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    async def fetch_latest(self, symbol: str) -> dict[str, Any]:
        ticker = await self._exchange.fetch_ticker(symbol)
        return {
            "symbol": symbol,
            "price": ticker["last"],
            "timestamp": ticker["timestamp"],
            "volume_24h": ticker.get("quoteVolume"),
        }

    def supported_symbols(self) -> list[str]:
        return [
            "BTC_USDT", "ETH_USDT", "SOL_USDT", "GT_USDT", "XRP_USDT",
        ]

    def can_resolve(self, symbol: str) -> bool:
        s = symbol.upper()
        return s.endswith("USDT") or "_" in s

    async def close(self) -> None:
        await self._exchange.close()
