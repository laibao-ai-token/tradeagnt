"""Symbol helpers for CN fund collection."""

from __future__ import absolute_import


def normalize_cn_fund_symbol(symbol):
    value = str(symbol or "").strip().upper()
    if not value:
        return ""
    value = value.replace("/", "").replace("-", "").replace("_", "")
    if value.endswith(".SH"):
        value = "SH" + value[:-3]
    elif value.endswith(".SZ"):
        value = "SZ" + value[:-3]

    if value.startswith(("SH", "SZ")):
        digits = "".join([char for char in value[2:] if char.isdigit()])
        if len(digits) == 6:
            return value[:2] + digits
        return ""

    digits = "".join([char for char in value if char.isdigit()])
    if len(digits) != 6:
        return ""
    return digits


def _infer_cn_fund_exchange(code):
    normalized = normalize_cn_fund_symbol(code)
    if not normalized or not normalized.isdigit():
        return ""
    if normalized[0] in ("5", "6", "9"):
        return "SH"
    if normalized.startswith(("15", "16", "18")):
        return "SZ"
    return ""


def cn_fund_exchange_candidates(symbol):
    normalized = normalize_cn_fund_symbol(symbol)
    if not normalized:
        return []
    if normalized.startswith(("SH", "SZ")):
        return [normalized]
    exchange = _infer_cn_fund_exchange(normalized)
    if not exchange:
        return []
    return ["{0}{1}".format(exchange, normalized)]
