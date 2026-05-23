"""Market-aware symbol normalization."""
from __future__ import annotations

from tradecat.core.symbols.crypto import crypto_pair_to_compact, normalize_crypto_pair
from tradecat.core.symbols.equity import is_us_ticker, normalize_us_ticker

_MARKET_ALIASES = {
    "crypto": "crypto",
    "crypto_spot": "crypto",
    "us": "us_stock",
    "us_stock": "us_stock",
    "equity_us": "us_stock",
}

# 裸符号易与美股 ticker 冲突的常见 crypto base（自动识别时排除）
_CRYPTO_BASES = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "XRP",
        "ADA",
        "DOGE",
        "DOT",
        "AVAX",
        "MATIC",
        "LINK",
        "LTC",
        "BCH",
        "UNI",
        "GT",
        "TRX",
        "ATOM",
        "ETC",
        "FIL",
    }
)


def normalize_market(market: str) -> str:
    return _MARKET_ALIASES.get((market or "").strip().lower(), (market or "").strip().lower())


def normalize_symbol(symbol: str, market: str | None = None) -> str:
    """Normalize symbol for the given market; auto-detect when market is empty."""
    m = normalize_market(market) if market else ""
    raw = (symbol or "").strip()
    if not raw:
        return ""

    if m == "us_stock":
        return normalize_us_ticker(raw)
    if m == "crypto":
        return normalize_crypto_pair(raw)

    # Auto-detect: 显式 crypto 形态 → 否则优先美股 ticker → 再 crypto
    t = raw.strip().upper()
    if "_" in t or "/" in t or "-" in t.replace(".", "") or t.endswith("USDT"):
        return normalize_crypto_pair(raw)
    us = normalize_us_ticker(raw)
    if us and us not in _CRYPTO_BASES:
        return us
    return normalize_crypto_pair(raw)


def normalize_symbols_for_strategy(symbols: list[str], market: str) -> list[str]:
    """Normalize and dedupe strategy symbol list."""
    m = normalize_market(market)
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols:
        norm = normalize_symbol(s, m)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def default_provider_for_market(market: str) -> str:
    m = normalize_market(market)
    if m == "us_stock":
        return "us_equity"
    return "gate"


def default_symbols_for_market(market: str) -> list[str]:
    """Fallback symbols when strategy list is empty."""
    m = normalize_market(market)
    if m == "us_stock":
        return ["NVDA", "META", "ORCL"]
    return ["BTC_USDT", "ETH_USDT"]


def infer_market_from_symbol(symbol: str) -> str:
    """Infer market from symbol shape (us_stock vs crypto)."""
    norm = normalize_symbol(symbol)
    if not norm:
        return "crypto"
    if normalize_us_ticker(norm):
        return "us_stock"
    return "crypto"


def is_close_only_sell(market: str) -> bool:
    """Stock cash markets: SELL closes long instead of opening short."""
    return normalize_market(market) == "us_stock"


def signal_symbol_for_engine(symbol: str, market: str) -> str:
    """Symbol passed into SignalEngine / provider (crypto may use compact form)."""
    m = normalize_market(market)
    norm = normalize_symbol(symbol, m)
    if not norm:
        return ""
    if m == "crypto":
        return crypto_pair_to_compact(norm) or norm
    return norm


__all__ = [
    "crypto_pair_to_compact",
    "default_provider_for_market",
    "default_symbols_for_market",
    "infer_market_from_symbol",
    "is_close_only_sell",
    "is_us_ticker",
    "normalize_crypto_pair",
    "normalize_market",
    "normalize_symbol",
    "normalize_symbols_for_strategy",
    "normalize_us_ticker",
    "signal_symbol_for_engine",
]
