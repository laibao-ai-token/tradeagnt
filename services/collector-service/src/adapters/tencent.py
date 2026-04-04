"""Minimal Tencent CN quote adapter for fund/equity snapshot collection."""

from __future__ import absolute_import

import re

TENCENT_LINE_RE = re.compile(r'^v_(?:sh|sz)\d{6}=')


def _to_float(value):
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _parse_amount_field(value):
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    multiplier = 1.0
    if raw.endswith("万"):
        raw = raw[:-1]
        multiplier = 10000.0
    elif raw.endswith("亿"):
        raw = raw[:-1]
        multiplier = 100000000.0
    return _to_float(raw) * multiplier


def normalize_cn_symbol(symbol):
    value = str(symbol or "").strip().upper()
    if not value:
        return ""
    if value.endswith(".SH"):
        value = "SH" + value[:-3]
    elif value.endswith(".SZ"):
        value = "SZ" + value[:-3]
    if not value.startswith(("SH", "SZ")):
        return ""
    digits = "".join([char for char in value[2:] if char.isdigit()])
    if len(digits) != 6:
        return ""
    return value[:2] + digits


def parse_tencent_cn_quote_line(line):
    """Parse one Tencent CN quote line into a normalized dict."""

    text = str(line or "").strip()
    if not text or "=" not in text or '"' not in text or not TENCENT_LINE_RE.search(text):
        return None

    payload = text.split('"', 2)[1]
    parts = payload.split("~")
    if len(parts) < 31:
        return None

    prefix = text.split("=", 1)[0].strip().replace("v_", "")
    exchange = prefix[:2].lower()
    if exchange not in ("sh", "sz"):
        return None
    code = "".join([char for char in prefix[2:] if char.isdigit()])
    if len(code) != 6:
        return None

    symbol = "{0}{1}".format(exchange.upper(), code)
    amount = _parse_amount_field(parts[35] if len(parts) > 35 else "")
    if amount <= 0 and len(parts) > 37:
        amount = _to_float(parts[37]) * 10000.0

    return {
        "symbol": symbol,
        "name": (parts[1] or symbol).strip() or symbol,
        "price": _to_float(parts[3] if len(parts) > 3 else ""),
        "prev_close": _to_float(parts[4] if len(parts) > 4 else ""),
        "open": _to_float(parts[5] if len(parts) > 5 else ""),
        "high": _to_float(parts[33] if len(parts) > 33 else ""),
        "low": _to_float(parts[34] if len(parts) > 34 else ""),
        "volume": _to_float(parts[36] if len(parts) > 36 else ""),
        "amount": amount,
        "ts": str(parts[30] if len(parts) > 30 else "").strip(),
        "source": "tencent",
        "currency": "CNY",
    }


def _default_fetch_text(url, timeout_s, proxy=""):
    import requests

    kwargs = {"timeout": float(timeout_s)}
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    response = requests.get(url, **kwargs)
    response.raise_for_status()
    response.encoding = "gbk"
    return response.text


def fetch_tencent_cn_quotes(symbols, timeout_s=3.0, proxy="", fetch_text=None):
    """Batch fetch Tencent CN quotes keyed by normalized SH/SZ symbol."""

    cleaned = []
    seen = set()
    for symbol in list(symbols or []):
        normalized = normalize_cn_symbol(symbol)
        if not normalized or normalized in seen:
            continue
        cleaned.append(normalized)
        seen.add(normalized)
    if not cleaned:
        return {}

    query = ",".join(["{0}{1}".format(item[:2].lower(), item[2:]) for item in cleaned])
    url = "https://qt.gtimg.cn/q={0}".format(query)
    text = (fetch_text or _default_fetch_text)(url, timeout_s, proxy=proxy)

    quotes = dict((symbol, None) for symbol in cleaned)
    for line in str(text or "").splitlines():
        parsed = parse_tencent_cn_quote_line(line)
        if parsed is None:
            continue
        symbol = parsed["symbol"]
        if symbol in quotes:
            quotes[symbol] = parsed
    return quotes
