"""Binance Spot data provider (via ccxt)."""
from __future__ import annotations

from typing import Any

import ccxt.async_support as ccxt
import pandas as pd

from tradecat.core.providers.base import DataProvider


class BinanceProvider(DataProvider):
    """Binance spot market data provider."""

    def __init__(self) -> None:
        self._exchange = ccxt.binance({"options": {"defaultType": "spot"}})

    @property
    def name(self) -> str:
        return "binance"

    async def fetch_klines(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> pd.DataFrame:
        """Fetch OHLCV from Binance and return a standardised DataFrame."""
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
        # Core liquid pairs; full list can be fetched dynamically in the future.
        return [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT",
        ]

    def can_resolve(self, symbol: str) -> bool:
        return symbol.upper().endswith("USDT")

    async def close(self) -> None:
        await self._exchange.close()
