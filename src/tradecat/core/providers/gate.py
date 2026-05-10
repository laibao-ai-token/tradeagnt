"""Gate.io data provider (via ccxt)."""
from __future__ import annotations

from tradecat.core.providers.ccxt_base import CCXTProvider


class GateProvider(CCXTProvider):
    """Gate.io spot market data provider."""

    def __init__(self) -> None:
        super().__init__("gateio")

    @property
    def name(self) -> str:
        return "gate"

    def supported_symbols(self) -> list[str]:
        return [
            "BTC_USDT", "ETH_USDT", "SOL_USDT", "GT_USDT", "XRP_USDT",
        ]

    def can_resolve(self, symbol: str) -> bool:
        s = symbol.upper()
        return s.endswith("USDT") or "_USDT" in s
