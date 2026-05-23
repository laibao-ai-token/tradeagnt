"""US equity HTTP fetchers for core providers (no TUI import)."""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_SAFE_YAHOO_SYMBOL_RE = re.compile(r"^[A-Z0-9.^=\-]{1,32}$")
_TENCENT_PREFIX_RE = re.compile(r"^v_([a-zA-Z]+)")

_NASDAQ_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "referer": "https://charting.nasdaq.com/dynamic/chart.html",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
}


@dataclass(frozen=True)
class UsSpotQuote:
    symbol: str
    price: float
    volume: float
    currency: str
    source: str


def _to_float(raw: str) -> float:
    try:
        return float(raw)
    except Exception:
        return 0.0


def _http_get(url: str, *, timeout_s: float = 6.0, headers: dict[str, str] | None = None) -> str:
    hdrs = {
        "User-Agent": "TradeCat/core",
        "Accept": "*/*",
        "Connection": "close",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method="GET")

    def _read(force_ipv4: bool) -> bytes:
        if not force_ipv4:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read()
        orig = socket.getaddrinfo

        def _ipv4(host, port, family=0, type=0, proto=0, flags=0):
            return orig(host, port, socket.AF_INET, type, proto, flags)

        socket.getaddrinfo = _ipv4  # type: ignore[assignment]
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read()
        finally:
            socket.getaddrinfo = orig  # type: ignore[assignment]

    try:
        data = _read(False)
    except urllib.error.URLError as exc:
        errno = getattr(getattr(exc, "reason", None), "errno", None)
        if errno in {101, 113, 99}:
            data = _read(True)
        else:
            raise
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace")


def fetch_nasdaq_us_minute_series(symbol: str, timeout_s: float = 6.0, limit: int = 60) -> list[tuple[int, float, float]]:
    sym = (symbol or "").strip().upper()
    if sym.endswith(".US") and len(sym) > 3:
        sym = sym[:-3]
    if not sym or not _SAFE_TOKEN_RE.match(sym):
        return []
    url = (
        "https://charting.nasdaq.com/data/charting/intraday"
        f"?symbol={sym}&mostRecent=1&includeLatestIntradayData=1"
    )
    try:
        payload = _http_get(url, timeout_s=timeout_s, headers=_NASDAQ_HEADERS)
        obj = json.loads(payload)
    except Exception:
        return []
    rows = obj.get("marketData") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        return []
    try:
        from zoneinfo import ZoneInfo

        ny_tz = ZoneInfo("America/New_York")
    except Exception:
        return []
    out: list[tuple[int, float, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_raw = str(row.get("Date") or "").strip()
        price = _to_float(str(row.get("Value") or ""))
        if not ts_raw or price <= 0:
            continue
        try:
            dt = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ny_tz)
        except ValueError:
            continue
        volume = _to_float(str(row.get("Volume") or ""))
        out.append((int(dt.timestamp()), price, max(0.0, volume)))
    out.sort(key=lambda x: x[0])
    return out[-max(5, int(limit)) :]


def fetch_tencent_us_quote(symbol: str, timeout_s: float = 5.0) -> UsSpotQuote | None:
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    url = f"https://qt.gtimg.cn/q=us{sym}"
    try:
        text = _http_get(url, timeout_s=timeout_s)
    except Exception:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        m = _TENCENT_PREFIX_RE.search(line)
        if not m:
            continue
        payload = line.split('"', 2)[1]
        parts = payload.split("~")
        if len(parts) < 31:
            continue
        price = _to_float(parts[3])
        if price <= 0:
            continue
        volume = _to_float(parts[36]) if len(parts) > 36 else 0.0
        return UsSpotQuote(symbol=sym, price=price, volume=volume, currency="USD", source="tencent")
    return None


def fetch_yahoo_us_stock_quote(symbol: str, timeout_s: float = 6.0) -> UsSpotQuote | None:
    sym = (symbol or "").strip().upper()
    if not sym or not _SAFE_YAHOO_SYMBOL_RE.match(sym):
        return None
    encoded = urllib.parse.quote(sym, safe="")
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={encoded}"
    try:
        obj = json.loads(_http_get(url, timeout_s=timeout_s))
    except Exception:
        return None
    qr = obj.get("quoteResponse") if isinstance(obj, dict) else None
    rows = qr.get("result") if isinstance(qr, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    if not isinstance(row, dict):
        return None
    price = _to_float(str(row.get("regularMarketPrice") or row.get("price") or ""))
    if price <= 0:
        return None
    volume = _to_float(str(row.get("regularMarketVolume") or row.get("volume") or ""))
    return UsSpotQuote(symbol=sym, price=price, volume=volume, currency="USD", source="yahoo")


def fetch_tencent_us_minute_series(symbol: str, timeout_s: float = 8.0, limit: int = 120) -> list[tuple[int, float, float]]:
    """Fallback minute series via Tencent (US code usSYMBOL)."""
    sym = (symbol or "").strip().upper()
    if sym.endswith(".US") and len(sym) > 3:
        sym = sym[:-3]
    if not sym:
        return []
    code = f"us{sym}"
    url = f"https://ifzq.gtimg.cn/appstock/app/minute/query?code={code}"
    try:
        payload = _http_get(url, timeout_s=timeout_s)
        obj = json.loads(payload)
    except Exception:
        return []
    block = obj.get("data", {}).get(code, {}) if isinstance(obj, dict) else {}
    data = block.get("data") if isinstance(block, dict) else {}
    rows = data.get("data") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    date_raw = str(data.get("date") or "")
    if len(date_raw) != 8 or not date_raw.isdigit():
        return []
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/New_York")
        trade_date = datetime.strptime(date_raw, "%Y%m%d").date()
    except Exception:
        return []
    out: list[tuple[int, float, float]] = []
    for raw in rows:
        cols = str(raw or "").split()
        if len(cols) < 2:
            continue
        hhmm = cols[0]
        if len(hhmm) != 4 or not hhmm.isdigit():
            continue
        price = _to_float(cols[1])
        if price <= 0:
            continue
        vol = _to_float(cols[2]) if len(cols) > 2 else 0.0
        hh, mm = int(hhmm[:2]), int(hhmm[2:])
        ts = datetime(trade_date.year, trade_date.month, trade_date.day, hh, mm, tzinfo=tz)
        out.append((int(ts.timestamp()), price, max(0.0, vol)))
    out.sort(key=lambda x: x[0])
    return out[-max(5, int(limit)) :]
