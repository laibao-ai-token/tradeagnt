from __future__ import annotations

from tradecat.core.providers.base import DataProvider


class ProviderRegistry:
    """数据源提供者注册表."""

    def __init__(self) -> None:
        self._providers: list[DataProvider] = []

    def register(self, provider: DataProvider) -> None:
        """注册一个新的数据源提供者."""
        self._providers.append(provider)

    def resolve(self, symbol: str) -> DataProvider:
        """根据 symbol 解析并返回能够处理它的 DataProvider."""
        for provider in self._providers:
            if provider.can_resolve(symbol):
                return provider
        raise ValueError(f"No provider can resolve symbol: {symbol}")

    def list_providers(self) -> list[DataProvider]:
        """返回所有已注册的 provider 列表（副本）."""
        return self._providers.copy()
