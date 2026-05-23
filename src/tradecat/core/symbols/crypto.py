"""Crypto pair symbol normalization (Gate-style BASE_QUOTE)."""
from __future__ import annotations

import re

_CRYPTO_PAIR_RE = re.compile(r"^[A-Z0-9]{2,12}_[A-Z0-9]{2,12}$")


def normalize_crypto_pair(symbol: str) -> str:
    """Normalize to ``BASE_QUOTE`` (e.g. ``BTC_USDT``). Accepts ``BTCUSDT``, ``BTC-USDT``, etc."""
    t = (symbol or "").strip().upper()
    if not t:
        return ""
    t = t.replace("/", "_").replace("-", "_")
    if "_" not in t:
        if t.endswith("USDT") and len(t) > 4:
            t = t[:-4] + "_USDT"
        elif t.isalnum() and 2 <= len(t) <= 12:
            t = f"{t}_USDT"
    if not _CRYPTO_PAIR_RE.match(t):
        return ""
    return t


def crypto_pair_to_compact(symbol: str) -> str:
    """``BTC_USDT`` -> ``BTCUSDT`` for providers/strategies that use compact codes."""
    pair = normalize_crypto_pair(symbol)
    return pair.replace("_", "") if pair else ""
