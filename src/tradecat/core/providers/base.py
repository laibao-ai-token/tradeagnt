from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class DataProvider(ABC):
    """数据源插件抽象基类."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 唯一标识名称."""
        ...

    @abstractmethod
    async def fetch_klines(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> pd.DataFrame:
        """获取 K 线数据.

        返回标准 DataFrame, 列包含: timestamp, open, high, low, close, volume.
        """
        ...

    @abstractmethod
    async def fetch_latest(self, symbol: str) -> dict[str, Any]:
        """获取最新报价（tick 级别）."""
        ...

    @abstractmethod
    def supported_symbols(self) -> list[str]:
        """返回该 Provider 支持的所有 symbol 列表."""
        ...

    @abstractmethod
    def can_resolve(self, symbol: str) -> bool:
        """判断该 provider 是否支持给定的 symbol."""
        ...
