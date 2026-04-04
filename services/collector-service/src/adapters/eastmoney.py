"""Minimal Eastmoney fund valuation adapter for off-market CN funds."""

from __future__ import absolute_import

import json
import re
from datetime import datetime

SAFE_CN_FUND_CODE_RE = re.compile(r"^\d{6}$")


def _to_float(value):
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def parse_fundgz_jsonp(payload):
    """Parse `jsonpgz({...});` payload into a normalized quote dict."""

    text = str(payload or "").strip()
    if not text:
        return None
    match = re.search(r"\((\{.*\})\)\s*;?\s*$", text, flags=re.S)
    if not match:
        return None
    try:
        item = json.loads(match.group(1))
    except Exception:
        return None
    if not isinstance(item, dict):
        return None

    code = str(item.get("fundcode") or "").strip()
    if not SAFE_CN_FUND_CODE_RE.match(code):
        return None
    name = str(item.get("name") or code).strip() or code
    estimated_nav = _to_float(item.get("gsz"))
    nav = _to_float(item.get("dwjz"))
    price = estimated_nav if estimated_nav > 0 else nav
    if price <= 0:
        return None
    prev_close = nav if nav > 0 else price
    change_pct = _to_float(item.get("gszzl"))
    if prev_close > 0:
        open_price = prev_close
    elif abs(change_pct) > 1e-9:
        open_price = price / max(1e-9, (1 + change_pct / 100.0))
    else:
        open_price = price

    ts = str(item.get("gztime") or "").strip()
    if ts and len(ts) == 16:
        ts = "{0}:00".format(ts)
    if not ts:
        trade_date = str(item.get("jzrq") or "").strip()
        if trade_date:
            ts = "{0} 15:00:00".format(trade_date)
        else:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "symbol": code,
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "open": open_price,
        "high": price,
        "low": price,
        "volume": 0.0,
        "amount": 0.0,
        "ts": ts,
        "source": "fundgz",
        "currency": "CNY",
    }


def _default_fetch_text(url, timeout_s, proxy="", headers=None):
    import requests

    kwargs = {
        "timeout": float(timeout_s),
        "headers": headers or {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": url,
            "Accept": "application/javascript,text/javascript,*/*;q=0.1",
        },
    }
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    response = requests.get(url, **kwargs)
    response.raise_for_status()
    return response.text


def fetch_fundgz_quote(code, timeout_s=3.0, proxy="", fetch_text=None):
    """Fetch off-market fund valuation quote by 6-digit code."""

    normalized = str(code or "").strip()
    if not SAFE_CN_FUND_CODE_RE.match(normalized):
        return None
    url = "https://fundgz.1234567.com.cn/js/{0}.js".format(normalized)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://fund.eastmoney.com/{0}.html".format(normalized),
        "Accept": "application/javascript,text/javascript,*/*;q=0.1",
    }
    text = (fetch_text or _default_fetch_text)(url, timeout_s, proxy=proxy, headers=headers)
    return parse_fundgz_jsonp(text)
