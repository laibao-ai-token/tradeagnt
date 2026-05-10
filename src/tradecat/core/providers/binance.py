"""Binance Spot data provider (via ccxt)."""
from __future__ import annotations

from tradecat.core.providers.ccxt_base import CCXTProvider


class BinanceProvider(CCXTProvider):
    """Binance spot market data provider."""

    def __init__(self) -> None:
        super().__init__("binance")

    @property
    def name(self) -> str:
        return "binance"

    def supported_symbols(self) -> list[str]:
        return [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT",
        ]
