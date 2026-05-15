from __future__ import annotations


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _infer_cn_fund_exchange(code: str) -> str:
    if not code or not code.isdigit() or len(code) != 6:
        return ""
    if code[0] in {"5", "6", "9"}:
        return "SH"
    if code.startswith(("15", "16", "18")):
        return "SZ"
    return ""


def _cn_stock_style_exchange_form(symbol: str) -> str:
    """
    Keep compatibility with legacy TUI matching:
    - Bare 6-digit non-SH-leading codes are treated as SZ when matching.
    """
    sym = normalize_cn_fund_symbol(symbol)
    if not sym:
        return ""
    if sym.startswith(("SH", "SZ")):
        return sym
    if len(sym) == 6 and sym.isdigit():
        if sym[0] in {"5", "6", "9"}:
            return "SH" + sym
        return "SZ" + sym
    return ""


def normalize_cn_fund_symbol(symbol: str) -> str:
    """
    Normalize one CN fund symbol.

    Supported inputs:
    - Exchange-traded ETF/LOF: SH510300 / SZ159915 / 510300.SH / 159915.SZ
    - Off-market fund code: 024389
    - Raw 6-digit code is preserved (for mixed watchlist semantics).
    """
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    s = s.replace("/", "").replace("-", "").replace("_", "")
    if s.endswith(".SH"):
        s = "SH" + s[:-3]
    elif s.endswith(".SZ"):
        s = "SZ" + s[:-3]

    if s.startswith(("SH", "SZ")):
        digits = "".join(ch for ch in s[2:] if ch.isdigit())
        if len(digits) == 6:
            return s[:2] + digits
        return ""

    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) != 6:
        return ""
    return digits


def normalize_cn_fund_symbols_csv(raw: str) -> list[str]:
    out: list[str] = []
    for token in (raw or "").replace(" ", "").split(","):
        sym = normalize_cn_fund_symbol(token)
        if not sym:
            continue
        out.append(sym)
    return _dedup_keep_order(out)


def cn_fund_exchange_candidates(symbol: str) -> list[str]:
    sym = normalize_cn_fund_symbol(symbol)
    if not sym:
        return []
    if sym.startswith(("SH", "SZ")):
        return [sym]
    ex = _infer_cn_fund_exchange(sym)
    if not ex:
        return []
    return [ex + sym]


def match_cn_fund_signal(signal_symbol: str, quote_symbol: str) -> bool:
    signal = normalize_cn_fund_symbol(signal_symbol)
    quote = normalize_cn_fund_symbol(quote_symbol)
    if not signal or not quote:
        return False

    if signal == quote:
        return True

    signal_cands = cn_fund_exchange_candidates(signal)
    quote_cands = cn_fund_exchange_candidates(quote)
    if quote in signal_cands:
        return True
    if signal in quote_cands:
        return True
    if signal_cands and quote_cands:
        return bool(set(signal_cands) & set(quote_cands))

    # Compatibility fallback: keep legacy SZ default for bare 6-digit non-SH-leading
    # codes when the compared side is exchange-prefixed.
    signal_stock_form = _cn_stock_style_exchange_form(signal)
    quote_stock_form = _cn_stock_style_exchange_form(quote)
    if signal_stock_form and quote_stock_form:
        return signal_stock_form == quote_stock_form
    return False
