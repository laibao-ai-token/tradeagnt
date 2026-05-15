from __future__ import annotations

from tradecat.core.providers.base import DataProvider


class ProviderRegistry:
    """数据源提供者注册表（支持自动发现）."""

    def __init__(self) -> None:
        self._providers: list[DataProvider] = []

    def register(self, provider: DataProvider) -> None:
        """注册一个新的数据源提供者."""
        if any(p.name == provider.name for p in self._providers):
            raise ValueError(f"Provider '{provider.name}' is already registered.")
        self._providers.append(provider)

    def resolve(self, symbol: str) -> DataProvider:
        """根据 symbol 解析并返回能够处理它的 DataProvider."""
        for provider in self._providers:
            if provider.can_resolve(symbol):
                return provider
        raise ValueError(f"No provider can resolve symbol: {symbol}")

    def resolve_by_name(self, name: str) -> DataProvider:
        """根据 provider 名称精确选择."""
        for provider in self._providers:
            if provider.name == name:
                return provider
        raise ValueError(f"No provider named: {name}. Registered: {[p.name for p in self._providers]}")

    def list_providers(self) -> list[DataProvider]:
        """返回所有已注册的 provider 列表（副本）."""
        return self._providers.copy()

    def auto_register(self) -> None:
        """自动注册所有内置 Provider."""
        from tradecat.core.providers.binance import BinanceProvider
        from tradecat.core.providers.gate import GateProvider
        self.register(BinanceProvider())
        self.register(GateProvider())
