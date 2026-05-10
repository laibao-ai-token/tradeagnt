from tradecat.core.providers.base import DataProvider
from tradecat.core.providers.ccxt_base import CCXTProvider
from tradecat.core.providers.registry import ProviderRegistry


def __getattr__(name: str):  # lazy import: avoids loading ccxt+httpx at startup
    if name == "BinanceProvider":
        from tradecat.core.providers.binance import BinanceProvider
        return BinanceProvider
    if name == "GateProvider":
        from tradecat.core.providers.gate import GateProvider
        return GateProvider
    if name == "RSSNewsProvider":
        from tradecat.core.providers.rss_news import RSSNewsProvider
        return RSSNewsProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DataProvider",
    "CCXTProvider",
    "ProviderRegistry",
    "BinanceProvider",
    "GateProvider",
    "RSSNewsProvider",
]
