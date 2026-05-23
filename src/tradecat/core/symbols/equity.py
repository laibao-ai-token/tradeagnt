"""US equity ticker normalization."""
from __future__ import annotations

import re

_US_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,12}$")


def normalize_us_ticker(symbol: str) -> str:
    """Normalize to bare US ticker (e.g. ``NVDA``, ``BRK.B``)."""
    t = (symbol or "").strip().upper()
    if not t:
        return ""
    if t.endswith(".US") and len(t) > 3:
        t = t[:-3]
    if "/" in t or "_" in t:
        return ""
    if not _US_TICKER_RE.match(t):
        return ""
    return t


def is_us_ticker(symbol: str) -> bool:
    return bool(normalize_us_ticker(symbol))
