"""DataProvider 骨架 — 复制到 src/tradecat/core/providers/<market>_equity.py 后实现。

请勿直接 import 本文件；仅作文档模板。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from tradecat.core.providers.base import DataProvider

# from tradecat.core.symbols.xx import normalize_xx_symbol, is_xx_symbol


class XxEquityProvider(DataProvider):
    """TODO: 填写市场名与数据能力说明（timeframe、历史深度、数据源）."""

    @property
    def name(self) -> str:
        return "xx_equity"  # TODO: 与 default_provider_for_market 一致

    async def fetch_klines(
        self, symbol: str, timeframe: str = "5m", limit: int = 100
    ) -> pd.DataFrame:
        return await asyncio.to_thread(self._fetch_klines_sync, symbol, timeframe, limit)

    def _fetch_klines_sync(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        # sym = normalize_xx_symbol(symbol)
        # TODO: 调用 tui/quote 或 PG，构建 OHLCV，必要时 resample
        # return df  # columns: timestamp, open, high, low, close, volume
        raise NotImplementedError

    async def fetch_latest(self, symbol: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._fetch_latest_sync, symbol)

    def _fetch_latest_sync(self, symbol: str) -> dict[str, Any]:
        # TODO: tui/quote fetch_* 
        return {"symbol": symbol, "price": 0.0, "volume_24h": 0.0}

    def supported_symbols(self) -> list[str]:
        return []  # TODO: 可选的示例列表

    def can_resolve(self, symbol: str) -> bool:
        # return is_xx_symbol(symbol)
        raise NotImplementedError

    async def close(self) -> None:
        pass
