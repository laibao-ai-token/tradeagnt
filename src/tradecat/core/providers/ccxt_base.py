"""Base class for ccxt-based crypto exchange providers."""
from __future__ import annotations

from abc import abstractmethod
from typing import Any

import ccxt.async_support as ccxt
import pandas as pd

from tradecat.core.providers.base import DataProvider


class CCXTProvider(DataProvider):
    """Shared implementation for ccxt-based spot market providers."""

    def __init__(self, exchange_id: str, default_type: str = "spot") -> None:
        self._exchange = getattr(ccxt, exchange_id)(
            {"options": {"defaultType": default_type}}
        )

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    async def fetch_klines(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> pd.DataFrame:
        try:
            ohlcv = await self._exchange.fetch_ohlcv(
                symbol, timeframe, limit=limit
            )
            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], unit="ms", utc=True
            )
            return df
        except ccxt.NetworkError as e:
            raise ConnectionError(
                f"[{self.name}] Network error fetching {symbol}: {e}"
            ) from e
        except ccxt.ExchangeError as e:
            raise RuntimeError(
                f"[{self.name}] Exchange error fetching {symbol}: {e}"
            ) from e

    async def fetch_latest(self, symbol: str) -> dict[str, Any]:
        try:
            ticker = await self._exchange.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "price": ticker["last"],
                "timestamp": ticker["timestamp"],
                "volume_24h": ticker.get("quoteVolume"),
            }
        except ccxt.NetworkError as e:
            raise ConnectionError(
                f"[{self.name}] Network error fetching {symbol}: {e}"
            ) from e
        except ccxt.ExchangeError as e:
            raise RuntimeError(
                f"[{self.name}] Exchange error fetching {symbol}: {e}"
            ) from e

    def can_resolve(self, symbol: str) -> bool:
        return symbol.upper().endswith("USDT")

    async def close(self) -> None:
        await self._exchange.close()
