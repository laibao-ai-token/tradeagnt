"""符号归一化骨架 — 复制到 src/tradecat/core/symbols/<market>.py 后实现。"""
from __future__ import annotations

import re

# TODO: 按市场调整正则
_SYMBOL_RE = re.compile(r"^TODO_PATTERN$")


def normalize_xx_symbol(symbol: str) -> str:
    """Return canonical symbol or empty string if invalid."""
    t = (symbol or "").strip().upper()
    if not t:
        return ""
    # TODO: 清洗规则
    if not _SYMBOL_RE.match(t):
        return ""
    return t


def is_xx_symbol(symbol: str) -> bool:
    return bool(normalize_xx_symbol(symbol))
