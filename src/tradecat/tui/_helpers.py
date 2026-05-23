"""Shared TUI helpers — curses utilities, formatting, signal processing.

This module exists to break circular imports between tui.py and page modules.
"""
from __future__ import annotations

import curses
import math
import os
import re
import unicodedata
from datetime import datetime, timezone

from tradecat.tui.db import SignalRow, parse_ts
from tradecat.tui.micro import Candle
from tradecat.tui.quote import Quote


# ── Display width helpers ──

def _char_display_width(ch: str) -> int:
    if len(ch) != 1:
        return 0
    cp = ord(ch)
    if cp <= 0x7F:
        return 1
    if (0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F or
            0xFF00 <= cp <= 0xFFEF or 0x3400 <= cp <= 0x4DBF):
        return 2
    return 1


def _text_display_width(text: str) -> int:
    return sum(_char_display_width(ch) for ch in text)


# ── Curses drawing helpers ──

def _safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    try:
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x < 0:
            return
        available = max_x - x
        if available <= 0:
            return
        win.addnstr(y, x, s, available, attr)
    except curses.error:
        pass


def _safe_vline(win, y: int, x: int, height: int, attr: int = 0) -> None:
    if height <= 0:
        return
    vline = _line_chars()[5]
    for i in range(height):
        _safe_addstr(win, y + i, x, vline, attr)


def _safe_hline(win, y: int, x: int, width: int, attr: int = 0) -> None:
    if width <= 0:
        return
    hline = _line_chars()[4]
    _safe_addstr(win, y, x, hline * width, attr)


def _draw_box(win, x: int, y: int, width: int, height: int, attr: int = 0) -> None:
    if width < 2 or height < 2:
        return
    left, top = x, y
    right = x + width - 1
    bottom = y + height - 1
    tl, tr, bl, br, h, v = _line_chars()
    _safe_addstr(win, top, left, tl, attr)
    _safe_addstr(win, top, right, tr, attr)
    _safe_addstr(win, bottom, left, bl, attr)
    _safe_addstr(win, bottom, right, br, attr)
    _safe_hline(win, top, left + 1, max(0, width - 2), attr)
    _safe_hline(win, bottom, left + 1, max(0, width - 2), attr)
    _safe_vline(win, top + 1, left, max(0, height - 2), attr)
    _safe_vline(win, top + 1, right, max(0, height - 2), attr)


# ── Text formatting ──

def _truncate(s: str, width: int) -> str:
    if width <= 0:
        return ""
    result = []
    current_width = 0
    for ch in s:
        ch_width = 2 if ord(ch) > 0x7F else 1
        if current_width + ch_width > width:
            break
        result.append(ch)
        current_width += ch_width
    return "".join(result)


def _fit_cell(text: str, width: int, *, align: str = "left") -> str:
    tw = _text_display_width(text)
    if tw >= width:
        return _truncate(text, width)
    pad = width - tw
    if align == "right":
        return " " * pad + text
    if align == "center":
        return " " * (pad // 2) + text + " " * (pad - pad // 2)
    return text + " " * pad


def _line_chars() -> tuple[str, str, str, str, str, str]:
    return ("+", "+", "+", "+", "-", "|")


# ── Value coercion ──

def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_finite_number(value: object) -> bool:
    if value is None:
        return False
    try:
        import math
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


# ── Signal helpers ──

def _crypto_signal_symbol_to_pair(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace("_", "")
    if "/" in s:
        return s
    for quote in ("USDT", "BUSD", "USD", "BTC", "ETH", "EUR"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}/{quote}"
    return s


def _fmt_freshness(ts: str, now_dt: datetime) -> str:
    from dateutil import parser as _dp
    try:
        dt = _dp.parse(ts)
        delta = (now_dt - dt).total_seconds()
    except Exception:
        return "?"
    if delta < 60:
        return f"{int(delta)}s"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


def _fmt_duration_compact(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _signal_timestamp_now() -> str:
    """ISO timestamp in local timezone for signal_history persistence."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _signal_row_age_seconds(row: SignalRow, now_dt: datetime) -> int | None:
    ts_dt = parse_ts(row.timestamp)
    if ts_dt == datetime.min:
        return None
    return max(0, int((now_dt - ts_dt).total_seconds()))


def _count_recent_signal_rows(rows: list[SignalRow], now_dt: datetime, *, max_age_s: int) -> int:
    count = 0
    for row in rows:
        age = _signal_row_age_seconds(row, now_dt)
        if age is not None and age <= max_age_s:
            count += 1
    return count


def _split_signal_rows_by_age(
    rows: list[SignalRow],
    now_dt: datetime,
) -> tuple[list[tuple[SignalRow, int]], list[tuple[SignalRow, int]], list[tuple[SignalRow, int]]]:
    """Bucket signals: realtime <=5m, 1h <=1h, 12h <=12h (by local wall-clock age)."""
    realtime_rows: list[tuple[SignalRow, int]] = []
    h1_rows: list[tuple[SignalRow, int]] = []
    h12_rows: list[tuple[SignalRow, int]] = []
    for row in rows:
        age_s = _signal_row_age_seconds(row, now_dt)
        if age_s is None:
            continue
        pair = (row, age_s)
        if age_s <= 5 * 60:
            realtime_rows.append(pair)
        elif age_s <= 60 * 60:
            h1_rows.append(pair)
        elif age_s <= 12 * 60 * 60:
            h12_rows.append(pair)
    return realtime_rows, h1_rows, h12_rows


def _latest_signal_row(rows: list[SignalRow], now_dt: datetime) -> tuple[SignalRow, int] | None:
    best, best_age = None, None
    for row in rows:
        age = _signal_row_age_seconds(row, now_dt)
        if age is not None and (best_age is None or age < best_age):
            best, best_age = row, age
    return (best, best_age) if best is not None else None


def _window_signal_stats(rows: list[SignalRow], now_dt: datetime, *, windows_s: tuple[int, ...]) -> dict:
    stats = {}
    for w in windows_s:
        stats[w] = _count_recent_signal_rows(rows, now_dt, max_age_s=w)
    return stats


def _build_recent_signal_panel_title(rows: list[SignalRow], now_dt: datetime) -> str:
    age = _latest_signal_row(rows, now_dt)
    if age is None:
        return "最近信号"
    _, s = age
    return f"最近信号 ({_fmt_freshness(rows[0].timestamp, now_dt)}前)"


def _signals_for_symbol(rows: list[SignalRow], quote_symbol: str, market: str) -> list[SignalRow]:
    return [r for r in rows if _match_signal_to_symbol(r.symbol, quote_symbol, market)]


def _match_signal_to_symbol(signal_symbol: str, quote_symbol: str, market: str) -> bool:
    ss = (signal_symbol or "").upper().strip()
    qs = (quote_symbol or "").upper().strip()
    if not ss or not qs:
        return False
    if ss == qs:
        return True
    if market == "crypto":
        return _crypto_signal_symbol_to_pair(ss) == _crypto_signal_symbol_to_pair(qs)
    return False


# ── Display helpers ──

def _display_symbol(sym: str, market: str) -> str:
    if market == "crypto":
        return _crypto_signal_symbol_to_pair(sym)
    return sym


def _display_name(sym: str, q: Quote | None, market: str) -> str:
    if q and getattr(q, "name", None):
        return q.name
    return _display_symbol(sym, market)


def _market_display_name(market: str, fallback: str = "") -> str:
    mapping = {
        "market_us": "美股", "market_cn": "A股", "market_hk": "港股",
        "market_fund_cn": "基金", "market_micro": "加密", "market_news": "资讯",
        "market_backtest": "回测", "signals": "信号",
    }
    return mapping.get((market or "").strip().lower(), fallback or market)


def _view_display_name(view: str) -> str:
    mapping = {
        "signals": "信号", "quotes": "美股", "quotes_us": "美股", "quotes_hk": "港股",
        "quotes_cn": "A股", "quotes_crypto": "加密", "quotes_metals": "金属",
        "market_us": "美股", "market_cn": "A股", "market_hk": "港股",
        "market_fund_cn": "基金", "market_micro": "加密", "market_news": "资讯",
        "market_backtest": "回测",
    }
    return mapping.get((view or "").strip().lower(), view)


def _fmt_time(ts: str, *, assume_utc: bool = False) -> str:
    """Format timestamp in local wall-clock (matches TUI header clock)."""
    dt = parse_ts(ts, assume_utc=assume_utc)
    if dt == datetime.min:
        return "--:--:--"
    now = datetime.now()
    if dt.date() != now.date():
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%H:%M:%S")


def _fmt_date(ts: str) -> str:
    try:
        return ts[5:10] if len(ts) >= 10 else ts
    except Exception:
        return ts


def _fmt_quote_ts(ts: str) -> str:
    try:
        if len(ts) >= 19:
            return f"{ts[5:10]} {ts[11:19]}"
        return ts
    except Exception:
        return ts


def _fmt_quote_ts_date8(ts: str) -> str:
    try:
        return ts[2:10] if len(ts) >= 10 else ts
    except Exception:
        return ts


def _fmt_signed(v: float) -> str:
    if v > 0:
        return f"+{v:.2f}"
    return f"{v:.2f}"


def _fmt_vol(v: float) -> str:
    if abs(v) >= 1e9:
        return f"{v / 1e9:.1f}B"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:.0f}"


def _format_service_status_bar(status) -> str:
    parts = []
    if hasattr(status, 'data_running'):
        parts.append(f"D:{status.data_running}/{status.data_total}")
    if hasattr(status, 'signal_up') and status.signal_up:
        parts.append("S:✓")
    if hasattr(status, 'trading_up') and status.trading_up:
        parts.append("T:✓")
    return " ".join(parts) if parts else ""


# ── Layout helpers ──

def _adaptive_left_min_width(total_width: int, *, base_min: int, floor_min: int, min_ratio: float) -> int:
    return max(floor_min, min(base_min, int(total_width * min_ratio)))


# ── Coercion helpers ──

def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_pct(value: object) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
        return v * 100 if abs(v) < 1 else v
    except (TypeError, ValueError):
        return None


def _extract_metric(payload: dict, keys: tuple[str, ...]) -> object | None:
    for k in keys:
        if k in payload:
            return payload[k]
    return None


def _resample_series(values: list[float], max_points: int) -> list[float]:
    if len(values) <= max_points:
        return values
    step = len(values) / max_points
    return [values[int(i * step)] for i in range(max_points)]


# ── Env ratio helper ──

def _read_env_ratio(name: str, default: float, min_value: float = 0.25, max_value: float = 0.60) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except Exception:
        return float(default)
    if not math.isfinite(value):
        return float(default)
    return max(float(min_value), min(float(max_value), float(value)))



# ── Market constants (moved from tui.py) ──
_CLOSED_CURVE_HISTORY_LIMIT = 60
_CLOSED_CURVE_RETRY_SECONDS = 120
_CLOSED_CURVE_STALE_SECONDS = 180
_CLOSED_CURVE_TARGET_SPAN_SECONDS = 45 * 60
_FUND_CN_CURVE_DAYS = max(5, int(os.environ.get("TUI_FUND_CN_CURVE_DAYS", "15")))
_FUND_CN_CURVE_REFRESH_SECONDS = max(30.0, float(os.environ.get("TUI_FUND_CN_CURVE_REFRESH_SECONDS", "300")))
_MARKET_MICRO_LEFT_BASE_MIN_WIDTH = 34
_MARKET_MICRO_LEFT_FLOOR_MIN_WIDTH = 24
_MARKET_MICRO_LEFT_MIN_RATIO = 0.24
_MARKET_MICRO_LEFT_RATIO = _read_env_ratio("TUI_MARKET_MICRO_LEFT_RATIO", 0.36)
_MARKET_MICRO_RIGHT_MIN_WIDTH = 28

# ── Page / tab constants ──
_MARKET_TABS = ["market_micro", "market_us", "market_cn", "market_hk", "market_fund_cn"]
_MARKET_TAB_LABELS = ["加密", "美股", "A股", "港股", "基金"]
# P1 主战场：←→ 与顶栏子标签仅循环加密 + 美股（A/HK/基金仍可用数字键 3/4/5 进入）
_MARKET_TABS_P1_PRIMARY = (0, 1)  # indices into _MARKET_TABS
_MARKET_TAB_LABELS_P1_PRIMARY = ["加密", "美股"]
_PAGE_NEWS_VIEW = "market_news"


def _cycle_p1_market_tab(market_tab: int, delta: int) -> int:
    """Cycle market_tab within primary P1 tabs (crypto, us)."""
    primary = list(_MARKET_TABS_P1_PRIMARY)
    try:
        idx = primary.index(market_tab)
    except ValueError:
        idx = 0
    return primary[(idx + delta) % len(primary)]

def _read_env_ratio(name: str, default: float, min_value: float = 0.25, max_value: float = 0.60) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except Exception:
        return float(default)
    if not math.isfinite(value):
        return float(default)
