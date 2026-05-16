"""Unified market panel drawing — replaces _draw_market_quad, _draw_market_fund_two_panel, _draw_market_micro."""
from __future__ import annotations

import curses
import time
from dataclasses import dataclass, field
from datetime import datetime

from .db import SignalRow, parse_ts
from .etf_profiles import get_domain_label, get_etf_domain_profile
from .etf_selector import select_etf_candidates
from .micro import Candle, MicroSnapshot

# Re-exported from tui.py — these will be passed in or imported after split
# For now, we import them from tui directly to avoid circular deps
# After the full split, these become imports from tui_format / tui_draw_common


# ─── Constants (duplicated from tui.py to avoid circular import) ───

_CLOSED_CURVE_STALE_SECONDS = 180
_CLOSED_CURVE_TARGET_SPAN_SECONDS = 45 * 60
_FUND_CN_CURVE_DAYS = max(5, int(__import__("os").environ.get("TUI_FUND_CN_CURVE_DAYS", "15")))
_MARKET_MICRO_LEFT_RATIO = 0.36
_MARKET_MICRO_LEFT_BASE_MIN_WIDTH = 34
_MARKET_MICRO_LEFT_FLOOR_MIN_WIDTH = 24
_MARKET_MICRO_LEFT_MIN_RATIO = 0.24
_MARKET_MICRO_RIGHT_MIN_WIDTH = 28


# ─── Helpers (duplicated from tui.py — will be deduplicated after split) ───

def _read_env_ratio(name: str, default: float, min_value: float = 0.25, max_value: float = 0.60) -> float:
    import os
    raw = os.environ.get(name, "")
    if raw:
        try:
            val = float(raw)
            return max(min_value, min(max_value, val))
        except (ValueError, TypeError):
            pass
    return default


def _adaptive_left_min_width(total_width: int, *, base_min: int, floor_min: int, min_ratio: float) -> int:
    return max(floor_min, min(base_min, int(total_width * min_ratio)))


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _is_finite_number(value: object) -> bool:
    if isinstance(value, (int, float)):
        return value == value and value != float("inf") and value != float("-inf")
    return False


def _char_display_width(ch: str) -> int:
    import unicodedata
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ("F", "W") else 1


def _text_display_width(text: str) -> int:
    return sum(_char_display_width(c) for c in text)


def _truncate(s: str, width: int) -> str:
    if width <= 0:
        return ""
    dw = _text_display_width(s)
    if dw <= width:
        return s
    result: list[str] = []
    cur = 0
    for ch in s:
        cw = _char_display_width(ch)
        if cur + cw > width - 1:
            break
        result.append(ch)
        cur += cw
    return "".join(result) + "~"


def _fit_cell(text: str, width: int, *, align: str = "left") -> str:
    if width <= 0:
        return ""
    truncated = _truncate(text, width)
    tw = _text_display_width(truncated)
    pad = max(0, width - tw)
    if align == "right":
        return " " * pad + truncated
    return truncated + " " * pad


def _safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        if x < 0:
            s = s[-x:]
            x = 0
        max_len = w - x
        if max_len <= 0:
            return
        win.addnstr(y, x, s, max_len, attr)
    except curses.error:
        pass


def _safe_vline(win, y: int, x: int, height: int, attr: int = 0) -> None:
    try:
        h, w = win.getmaxyx()
        if x < 0 or x >= w or y >= h:
            return
        for i in range(height):
            cy = y + i
            if 0 <= cy < h:
                win.addch(cy, x, curses.ACS_VLINE, attr)
    except curses.error:
        pass


def _safe_hline(win, y: int, x: int, width: int, attr: int = 0) -> None:
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        for i in range(width):
            cx = x + i
            if 0 <= cx < w:
                win.addch(y, cx, curses.ACS_HLINE, attr)
    except curses.error:
        pass


def _draw_box(win, x: int, y: int, width: int, height: int, attr: int = 0) -> None:
    if width < 2 or height < 2:
        return
    try:
        h, w = win.getmaxyx()
        if y < 0 or y + height > h or x < 0 or x + width > w:
            _safe_hline(win, y, x, width, attr)
            _safe_hline(win, y + height - 1, x, width, attr)
            _safe_vline(win, y, x, height, attr)
            _safe_vline(win, y, x + width - 1, height, attr)
            return
        win.attron(attr)
        win.border(
            curses.ACS_VLINE, curses.ACS_VLINE,
            curses.ACS_HLINE, curses.ACS_HLINE,
            curses.ACS_ULCORNER, curses.ACS_URCORNER,
            curses.ACS_LLCORNER, curses.ACS_LRCORNER,
        )
        win.attroff(attr)
    except curses.error:
        pass


def _line_chars() -> tuple[str, str, str, str, str, str]:
    return ("│", "─", "┌", "┐", "└", "┘")


def _fmt_time(ts: str) -> str:
    try:
        if "T" in ts:
            return ts.split("T")[1][:8]
        return ts[11:19] if len(ts) > 11 else ts
    except (IndexError, AttributeError):
        return ts


def _fmt_vol(v: float) -> str:
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return f"{v:.0f}"


def _display_symbol(sym: str, market: str) -> str:
    return sym


def _display_name(sym: str, q: object, market: str) -> str:
    return sym


def _signals_for_symbol(rows: list, symbol: str, market: str) -> list:
    return [r for r in rows if r.symbol == symbol]


def _count_recent_signal_rows(rows: list, now_dt: datetime, *, max_age_s: int) -> int:
    count = 0
    for row in rows:
        ts_dt = parse_ts(row.timestamp)
        if ts_dt != datetime.min:
            age = (now_dt - ts_dt).total_seconds()
            if 0 <= age <= max_age_s:
                count += 1
    return count


def _build_recent_signal_panel_title(rows: list, now_dt: datetime) -> str:
    if not rows:
        return "信号(0)"
    cnt = _count_recent_signal_rows(rows, now_dt, max_age_s=12 * 60 * 60)
    return f"信号({cnt})"


def _split_signal_rows_by_age(
    rows: list[SignalRow], now_dt: datetime
) -> tuple[list[tuple[SignalRow, int]], list[tuple[SignalRow, int]], list[tuple[SignalRow, int]]]:
    realtime: list[tuple[SignalRow, int]] = []
    h1: list[tuple[SignalRow, int]] = []
    h12: list[tuple[SignalRow, int]] = []
    for row in rows:
        ts_dt = parse_ts(row.timestamp)
        age_s = max(0, int((now_dt - ts_dt).total_seconds())) if ts_dt != datetime.min else 0
        pair = (row, age_s)
        if age_s <= 600:
            realtime.append(pair)
        elif age_s <= 3600:
            h1.append(pair)
        else:
            h12.append(pair)
    return realtime, h1, h12


def _snapshot_quote_curves(curves: dict) -> dict:
    return {k: list(v) for k, v in curves.items()}


def _signal_rows_signature(rows: list) -> tuple:
    if not rows:
        return (0,)
    first = rows[0]
    return (len(rows), first.id if hasattr(first, "id") else 0)


def _quote_book_signature(state) -> tuple:
    entries = state.entries if state else {}
    return (len(entries),)


def _curve_map_signature(curve_map: dict) -> tuple:
    return tuple(len(v) for v in curve_map.values())


def _micro_snapshot_signature(snapshot) -> tuple:
    if not snapshot:
        return (0,)
    return (len(getattr(snapshot, "symbols", [])),)


def _service_status_signature(status) -> tuple:
    return (0,)


# ─── Quote type stub for type hints ───
class Quote:
    price: float = 0.0
    prev_close: float = 0.0
    volume: float = 0.0
    ts: str = ""
    source: str = ""


# ─── Data types (duplicated from tui.py) ───

@dataclass
class QuoteEntryState:
    quote: object = None
    last_error: str = ""
    last_fetch_at: float = 0.0


@dataclass
class QuoteBookState:
    entries: dict[str, QuoteEntryState] = field(default_factory=dict)


@dataclass
class MasterPaneState:
    selected: int = 0
    left_scroll: int = 0
    right_scroll: int = 0
    focus: str = "left"


@dataclass
class QuoteConfig:
    symbols: list[str] = field(default_factory=list)
    enabled: bool = True
    market: str = ""


@dataclass
class FundDomainRuntimeState:
    keys: list[str] = field(default_factory=list)
    selected_idx: int = 0
    selected_key: str = ""


@dataclass
class RuntimeState:
    fund_domain: FundDomainRuntimeState = field(default_factory=FundDomainRuntimeState)


# ─── Market panel config ───

@dataclass
class MarketPanelConfig:
    """Configuration for the unified market panel."""
    mode: str  # "quad", "fund", "micro"

    # Column tiers: list of (min_width, columns) — first match wins
    column_tiers: list[tuple[int, list[tuple[str, str, int, str]]]] = field(default_factory=list)

    # Key hint text
    key_hint: str = ""

    # Whether to show domain column (fund mode)
    has_domain_column: bool = False
    domain_column_width: int = 10

    # Right bottom mode: "signals" or "details"
    right_bottom_mode: str = "signals"

    # Stats line mode: "standard", "fund", "micro"
    stats_mode: str = "standard"

    # Market label for display
    market: str = ""

    # Curve source: "live" or "daily"
    curve_source: str = "live"

    # Left panel ratio
    left_ratio: float = 0.38
    left_min_width: int = 30
    right_min_width: int = 28

    # Right top ratio
    right_top_ratio: float = 0.62


# ─── Preset configs ───

def quad_config(market: str = "") -> MarketPanelConfig:
    """Standard quad-panel config (US, HK, CN)."""
    return MarketPanelConfig(
        mode="quad",
        market=market,
        key_hint="按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 5基金 | 6港股 | 7资讯 | [/]切换 | +/-加减自选 | r刷新",
        column_tiers=[
            (56, [
                ("idx", "序", 3, "right"),
                ("code", "代码", 10, "left"),
                ("name", "名称", 1, "left"),
                ("last", "最新", 7, "right"),
                ("pct", "涨跌", 7, "right"),
                ("sig", "12h", 4, "right"),
            ]),
            (44, [
                ("idx", "序", 3, "right"),
                ("code", "代码", 10, "left"),
                ("name", "名称", 1, "left"),
                ("last", "最新", 7, "right"),
                ("pct", "涨跌", 7, "right"),
            ]),
            (34, [
                ("idx", "序", 3, "right"),
                ("code", "代码", 8, "left"),
                ("name", "名称", 1, "left"),
                ("pct", "涨跌", 7, "right"),
            ]),
            (0, [
                ("idx", "序", 3, "right"),
                ("name", "名称", 1, "left"),
                ("pct", "涨跌", 6, "right"),
            ]),
        ],
    )


def fund_config() -> MarketPanelConfig:
    """Fund domain two-panel config."""
    return MarketPanelConfig(
        mode="fund",
        market="",
        has_domain_column=True,
        domain_column_width=10,
        right_bottom_mode="details",
        stats_mode="fund",
        key_hint="按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 4回测切换 | 5基金 | 6港股 | 7资讯 | [/]切换标的 | ,.切换领域 | +/-加减自选 | r刷新",
        left_ratio=0.38,
        right_top_ratio=0.58,
        column_tiers=[
            (55, [
                ("cand", "候序", 4, "right"),
                ("code", "代码", 10, "left"),
                ("name", "名称", 1, "left"),
                ("last", "最新", 7, "right"),
                ("pct", "涨跌", 7, "right"),
                ("rank", "MRank", 5, "right"),
                ("score", "sRank", 6, "right"),
            ]),
            (38, [
                ("cand", "候序", 4, "right"),
                ("code", "代码", 10, "left"),
                ("name", "名称", 1, "left"),
                ("rank", "MRank", 5, "right"),
                ("score", "sRank", 6, "right"),
            ]),
            (30, [
                ("cand", "候", 3, "right"),
                ("code", "代码", 8, "left"),
                ("name", "名称", 1, "left"),
                ("rank", "MRk", 4, "right"),
                ("score", "sRk", 5, "right"),
            ]),
            (0, [
                ("cand", "候", 3, "right"),
                ("name", "名称", 1, "left"),
                ("rank", "MRk", 4, "right"),
                ("score", "sRk", 5, "right"),
            ]),
        ],
    )


def micro_config() -> MarketPanelConfig:
    """Micro/crypto config."""
    return MarketPanelConfig(
        mode="micro",
        market="crypto_spot",
        stats_mode="micro",
        key_hint="按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 4回测切换 | 5基金 | 6港股 | 7资讯 | [/]切换标的 | r刷新",
        left_ratio=_MARKET_MICRO_LEFT_RATIO,
        left_min_width=_MARKET_MICRO_LEFT_BASE_MIN_WIDTH,
        right_min_width=_MARKET_MICRO_RIGHT_MIN_WIDTH,
        right_top_ratio=0.62,
        column_tiers=[
            (56, [
                ("idx", "序", 3, "right"),
                ("code", "代码", 11, "left"),
                ("name", "名称", 1, "left"),
                ("last", "最新", 7, "right"),
                ("pct", "涨跌", 7, "right"),
                ("sig", "12h", 4, "right"),
            ]),
            (46, [
                ("idx", "序", 3, "right"),
                ("code", "代码", 11, "left"),
                ("name", "名称", 1, "left"),
                ("last", "最新", 7, "right"),
                ("pct", "涨跌", 7, "right"),
            ]),
            (36, [
                ("idx", "序", 3, "right"),
                ("code", "代码", 9, "left"),
                ("name", "名称", 1, "left"),
                ("last", "最新", 7, "right"),
                ("pct", "涨跌", 7, "right"),
            ]),
            (0, [
                ("idx", "序", 3, "right"),
                ("code", "代码", 9, "left"),
                ("last", "最新", 7, "right"),
            ]),
        ],
    )


# ─── Column resolution ───

def _resolve_columns(
    tiers: list[tuple[int, list[tuple[str, str, int, str]]]],
    inner_width: int,
) -> list[tuple[str, str, int, str]]:
    """Pick the first column tier whose min_width fits, then resolve dynamic 'name' column."""
    table_cols: list[tuple[str, str, int, str]] = tiers[-1][1] if tiers else []
    for min_w, cols in tiers:
        if inner_width >= min_w:
            table_cols = cols
            break

    fixed_w = sum(width for key, _, width, _ in table_cols if key != "name")
    field_count = len(table_cols)
    overhead_w = 2 + max(0, field_count - 1)
    resolved_name_w = max(1, inner_width - fixed_w - overhead_w)
    resolved: list[tuple[str, str, int, str]] = []
    for key, header, width, align in table_cols:
        if key == "name":
            resolved.append((key, header, resolved_name_w, align))
        else:
            resolved.append((key, header, width, align))
    return resolved


def _make_render_row(resolved_cols: list[tuple[str, str, int, str]], inner_width: int):
    """Create the _render_left_row closure (identical in all three original functions)."""
    def _render_left_row(prefix: str, values: dict[str, str]) -> str:
        cells = [_fit_cell(values.get(key, ""), width, align=align) for key, _, width, align in resolved_cols]
        body = " ".join(cells)
        return _fit_cell(f"{prefix} {body}", inner_width)
    return _render_left_row


# ─── Stats line rendering ───

def _render_stats_standard(selected_quote, selected_state, selected_curve) -> str:
    if selected_quote is None:
        return "价格=--  涨跌=--  幅度=--  成交量=--  延迟=--  模式=--"
    chg = selected_quote.price - selected_quote.prev_close
    pct = (chg / selected_quote.prev_close * 100.0) if selected_quote.prev_close else 0.0
    age_s = int(max(0.0, time.time() - (selected_state.last_fetch_at or 0.0))) if selected_state else 0

    curve_mode = "LIVE"
    quote_ts_dt = parse_ts(selected_quote.ts)
    if quote_ts_dt != datetime.min:
        quote_age_s = max(0, int(time.time() - quote_ts_dt.timestamp()))
        if quote_age_s >= _CLOSED_CURVE_STALE_SECONDS:
            curve_span_s = 0.0
            if len(selected_curve) >= 2:
                curve_span_s = max(0.0, float(selected_curve[-1].ts_open - selected_curve[0].ts_open))
            curve_mode = "CLOSE-1H" if curve_span_s >= _CLOSED_CURVE_TARGET_SPAN_SECONDS else "CLOSE"

    return (
        f"价格={selected_quote.price:.2f}  涨跌={chg:+.2f} ({pct:+.2f}%)  "
        f"成交量={_fmt_vol(selected_quote.volume)}  延迟={age_s}s  模式={curve_mode}"
    )


def _render_stats_fund(selected_quote, selected_state, selected_curve) -> str:
    if selected_quote is None:
        return "价格=--  涨跌=--  幅度=--  成交量=--  延迟=--  模式=--"
    chg = selected_quote.price - selected_quote.prev_close
    pct = (chg / selected_quote.prev_close * 100.0) if selected_quote.prev_close else 0.0
    age_s = int(max(0.0, time.time() - (selected_state.last_fetch_at or 0.0))) if selected_state else 0

    curve_mode = "LIVE"
    quote_ts_dt = parse_ts(selected_quote.ts)
    if quote_ts_dt != datetime.min:
        quote_age_s = max(0, int(time.time() - quote_ts_dt.timestamp()))
        if quote_age_s >= _CLOSED_CURVE_STALE_SECONDS:
            curve_span_s = 0.0
            if len(selected_curve) >= 2:
                curve_span_s = max(0.0, float(selected_curve[-1].ts_open - selected_curve[0].ts_open))
            target_days_span_s = max(24 * 3600, (_FUND_CN_CURVE_DAYS - 1) * 24 * 3600)
            if curve_span_s >= target_days_span_s:
                curve_mode = f"CLOSE-{_FUND_CN_CURVE_DAYS}D"
            elif curve_span_s >= _CLOSED_CURVE_TARGET_SPAN_SECONDS:
                curve_mode = "CLOSE-1H"
            else:
                curve_mode = "CLOSE"

    return (
        f"价格={selected_quote.price:.2f}  涨跌={chg:+.2f} ({pct:+.2f}%)  "
        f"成交量={_fmt_vol(selected_quote.volume)}  延迟={age_s}s  模式={curve_mode}  周期={_FUND_CN_CURVE_DAYS}D"
    )


def _render_stats_micro(selected_quote, selected_state, snapshot: MicroSnapshot | None) -> str:
    if selected_quote is None:
        return "价格=--  涨跌=--  成交量=--  延迟=--  源=--  模式=--"
    chg = selected_quote.price - selected_quote.prev_close
    pct = (chg / selected_quote.prev_close * 100.0) if selected_quote.prev_close else 0.0
    age_s = int(max(0.0, time.time() - (selected_state.last_fetch_at or 0.0))) if selected_state else 0
    src = (selected_quote.source or "--").upper()[:6]
    mode = "LIVE" if age_s <= 15 else ("SLOW" if age_s <= 120 else "STALE")
    # Compact format: single spaces, shorter labels to avoid truncation
    stats_line = (
        f"价格={selected_quote.price:.2f} 涨跌={chg:+.2f}({pct:+.2f}%) "
        f"量={_fmt_vol(selected_quote.volume)} 延={age_s}s 源={src} {mode}"
    )
    if snapshot and snapshot.symbol:
        bias = (snapshot.signals.bias or "NEUTRAL").upper()[:4]
        score = float(snapshot.signals.score)
        stats_line += f" 偏={bias} 评={score:+.1f}"
    return stats_line


# ─── Right bottom rendering ───

def _render_right_bottom_signals(
    stdscr,
    selected_rows: list[SignalRow],
    now_dt: datetime,
    colors: dict[str, int],
    right_inner_x: int,
    right_inner_y: int,
    right_inner_w: int,
    right_inner_h: int,
) -> None:
    """Render 3-column signal buckets (realtime, 1h, 12h)."""
    if right_inner_w < 30 or right_inner_h < 3:
        _safe_addstr(
            stdscr,
            right_inner_y,
            right_inner_x,
            _truncate("信号区过窄：请放大终端查看三列（5min/1h/12h）", right_inner_w),
            curses.color_pair(colors.get("SRC", 0)),
        )
        right_body_h = max(0, right_inner_h - 1)
        if selected_rows and right_body_h > 0:
            right_visible = selected_rows[: max(1, right_body_h)]
            for i, row in enumerate(right_visible):
                y = right_inner_y + 1 + i
                ts_dt = parse_ts(row.timestamp)
                age_s = max(0, int((now_dt - ts_dt).total_seconds())) if ts_dt != datetime.min else 0
                direction = (row.direction or "--").upper()[:4]
                tf = (row.timeframe or "--")[:3]
                strength = _safe_int(row.strength, 0)
                line = f"{_fmt_time(row.timestamp):<8} {age_s:>3}s {direction:<4}{strength:>3} {tf:<3}"
                _safe_addstr(stdscr, y, right_inner_x, _truncate(line, right_inner_w))
        return

    col_count = 3
    sep_count = col_count - 1
    usable_w = max(3, right_inner_w - sep_count)
    col_ws = [usable_w // col_count] * col_count
    for i in range(usable_w % col_count):
        col_ws[i] += 1
    col_xs = [right_inner_x]
    for i in range(1, col_count):
        col_xs.append(col_xs[-1] + col_ws[i - 1] + 1)
    sep_xs = [col_xs[1] - 1, col_xs[2] - 1]

    for sep_x in sep_xs:
        _safe_vline(stdscr, right_inner_y, sep_x, right_inner_h, curses.color_pair(colors.get("SRC", 0)))

    realtime_rows, h1_rows, h12_rows = _split_signal_rows_by_age(selected_rows, now_dt)

    buckets: list[tuple[str, list[tuple[SignalRow, int]]]] = [
        ("实时", realtime_rows),
        ("1h", h1_rows),
        ("12h", h12_rows),
    ]

    for i, (title, bucket_rows) in enumerate(buckets):
        header = f"{title}({len(bucket_rows)})"
        _safe_addstr(
            stdscr,
            right_inner_y,
            col_xs[i],
            _fit_cell(header, col_ws[i], align="left"),
            curses.A_UNDERLINE,
        )

    body_h = max(0, right_inner_h - 1)
    for i, (_title, bucket_rows) in enumerate(buckets):
        col_x = col_xs[i]
        col_w = col_ws[i]
        if body_h <= 0:
            continue
        if not bucket_rows:
            _safe_addstr(
                stdscr,
                right_inner_y + 1,
                col_x,
                _fit_cell("暂无", col_w, align="left"),
                curses.color_pair(colors.get("SRC", 0)),
            )
            continue

        for row_idx, (row, _age_s) in enumerate(bucket_rows[:body_h]):
            y = right_inner_y + 1 + row_idx
            direction = (row.direction or "--").upper()
            tf = (row.timeframe or "--")[:3]
            strength = _safe_int(row.strength, 0)
            if col_w >= 20:
                line = f"{_fmt_time(row.timestamp):<8} {direction[:4]:<4}{strength:>3} {tf:<3}"
            elif col_w >= 14:
                line = f"{_fmt_time(row.timestamp)[3:]:<5} {direction[:1]}{strength:>2} {tf:<3}"
            else:
                line = f"{direction[:1]}{strength:>2} {_fmt_time(row.timestamp)[3:]}"

            attr = 0
            if direction.startswith("BUY"):
                attr = curses.color_pair(colors.get("BUY", 0))
            elif direction.startswith("SELL"):
                attr = curses.color_pair(colors.get("SELL", 0))
            elif direction.startswith("ALER"):
                attr = curses.color_pair(colors.get("ALERT", 0))
            _safe_addstr(stdscr, y, col_x, _fit_cell(line, col_w, align="left"), attr)


def _render_right_bottom_details(
    stdscr,
    selected_symbol: str,
    selected_quote,
    selected_rows: list[SignalRow],
    quote_state: QuoteBookState,
    domain_top_symbols: tuple[str, ...],
    domain_label: str,
    model_rank_map: dict[str, int],
    model_item_map: dict[str, object],
    candidate_rank_map: dict[str, int],
    top_n_limit: int,
    ranking_snapshot,
    now_dt: datetime,
    right_x: int,
    right_bottom_y: int,
    right_w: int,
    right_bottom_h: int,
    market: str,
) -> None:
    """Render fund detail text in right bottom panel."""
    _safe_addstr(stdscr, right_bottom_y, right_x + 2, _truncate("选票信息 / TopN(领域优先+模型)", max(0, right_w - 4)), curses.A_UNDERLINE)
    details: list[str] = []
    details.append("口径说明: cnd=领域相关序 | MRank=模型排名 | sRank=模型总分")
    details.append("结论清单(编号+代码+名称+角色):")
    role_names = ("主选", "备选", "观察")
    conclusion_role_map: dict[str, str] = {}
    for idx, sym in enumerate(domain_top_symbols[: len(role_names)], start=1):
        role_name = role_names[idx - 1]
        conclusion_role_map[sym] = role_name
        rank_state = quote_state.entries.get(sym)
        code = _display_symbol(sym, market)
        name = _display_name(sym, rank_state.quote if rank_state else None, market)
        details.append(f"{idx}. {code} {name} | 角色={role_name}")
    if not conclusion_role_map:
        details.append("当前领域暂无可用结论清单")
    role = conclusion_role_map.get(selected_symbol)
    if role is not None:
        details.append(f"当前票定位: {role}（{domain_label}结论清单）")
    else:
        details.append(f"当前票定位: 非结论清单（{domain_label}候选池）")

    selected_rank = model_rank_map.get(selected_symbol)
    selected_item = model_item_map.get(selected_symbol)
    risk_map = {"LOW": "低", "MED": "中", "HIGH": "高"}

    if selected_item is None:
        details.append("当前状态: 暂无模型评分（数据缺失/过期）")
        details.append("提示: 可按 r 刷新，或等待行情更新")
    else:
        risk_txt = risk_map.get(selected_item.risk_level, selected_item.risk_level)
        cand_rank_txt = candidate_rank_map.get(selected_symbol)
        cand_rank_disp = str(cand_rank_txt) if cand_rank_txt is not None else "--"
        model_rank_disp = f"#{selected_rank}/{ranking_snapshot.valid_candidates}" if selected_rank is not None else "--"
        details.append(
            f"当前票: cnd={cand_rank_disp}  MRank={model_rank_disp}  sRank={selected_item.total_score:.1f}  风险={risk_txt}"
        )
        if cand_rank_txt is not None and selected_rank is not None and cand_rank_txt != selected_rank:
            details.append("提示: cnd 与 MRank 不必一致（相关度 vs 交易评分）")
        if selected_rank is not None and selected_rank > top_n_limit:
            details.append(f"前{top_n_limit}: 未入选（当前模型排名偏后）")
        details.append(
            f"因子: 趋势{selected_item.trend_score:.1f} 动量{selected_item.momentum_score:.1f} "
            f"流动{selected_item.liquidity_score:.1f} 风险{selected_item.risk_adjusted_score:.1f}"
        )
        details.append(f"标签: {' / '.join(selected_item.reason_tags[:3])}")

    if selected_rows:
        latest = selected_rows[0]
        latest_dir = (latest.direction or "--").upper()[:4]
        details.append(f"近期信号: {len(selected_rows)} | 最新={_fmt_time(latest.timestamp)} {latest_dir}")
    else:
        details.append("近期信号: 0（基金页以选票为主，信号仅作参考）")

    details.append(f"Top{top_n_limit}({domain_label}相关序):")
    for idx, sym in enumerate(domain_top_symbols, start=1):
        rank_state = quote_state.entries.get(sym)
        rank_name = _display_name(sym, rank_state.quote if rank_state else None, market)
        rank_symbol = _display_symbol(sym, market)
        item = model_item_map.get(sym)
        rank = model_rank_map.get(sym)
        rank_txt = f"#{rank}" if rank is not None else "--"
        score_txt = f"{item.total_score:.1f}" if item is not None else "--"
        details.append(f"{idx}. {rank_symbol:<10} {rank_name:<12} MRank={rank_txt} sRank={score_txt}")

    details.append(f"Top{top_n_limit}(模型评分,全池):")
    top_items = [model_item_map[s] for s in model_item_map if model_rank_map.get(s) is not None]
    top_items.sort(key=lambda x: model_rank_map.get(x.symbol, 999))
    for idx, item in enumerate(top_items[:top_n_limit], start=1):
        rank_symbol = _display_symbol(item.symbol, market)
        rank_state = quote_state.entries.get(item.symbol)
        rank_name = _display_name(item.symbol, rank_state.quote if rank_state else None, market)
        risk_txt = risk_map.get(item.risk_level, item.risk_level)
        details.append(f"{idx}. {rank_symbol:<10} {rank_name:<12} sRank={item.total_score:>5.1f} 风险={risk_txt}")

    right_body_h = max(0, right_bottom_h - 2)
    for i, line in enumerate(details[: max(1, right_body_h)]):
        _safe_addstr(stdscr, right_bottom_y + 1 + i, right_x + 1, _truncate(line, max(0, right_w - 2)))


# ─── Main unified function ───

def draw_market_panel(
    stdscr,
    config: MarketPanelConfig,
    symbols: list[str],
    selected_idx: int,
    quote_state: QuoteBookState,
    rows: list[SignalRow],
    colors: dict[str, int],
    curve_map: dict[str, list[Candle]],
    w: int,
    h: int,
    *,
    pane: MasterPaneState | None = None,
    domain_keys: list[str] | None = None,
    selected_domain_key: str = "",
    daily_curve_map: dict[str, list[Candle]] | None = None,
    micro_snapshot: MicroSnapshot | None = None,
    ranking_snapshot=None,
    model_rank_map: dict[str, int] | None = None,
    model_item_map: dict[str, object] | None = None,
    domain_top_symbols: tuple[str, ...] = (),
    top_n_limit: int = 0,
    domain_label: str = "",
    candidate_rank_map: dict[str, int] | None = None,
    refresh_s: float = 1.0,
) -> int:
    """Unified market panel drawing.

    Returns the new selected_idx.
    """
    # Key hint
    _safe_addstr(stdscr, h - 1, 0, _truncate(config.key_hint, w))

    # Empty state
    if not symbols:
        _safe_addstr(stdscr, 1, 0, _truncate("行情页：未启用或无标的", w))
        return 0

    selected_idx = min(max(0, selected_idx), max(0, len(symbols) - 1))
    selected_symbol = symbols[selected_idx]
    selected_state = quote_state.entries.get(selected_symbol)
    selected_quote = selected_state.quote if selected_state else None
    selected_rows = _signals_for_symbol(rows, selected_symbol, config.market)
    selected_curve = curve_map.get(selected_symbol, [])
    if config.curve_source == "daily" and daily_curve_map:
        selected_curve = daily_curve_map.get(selected_symbol) or selected_curve

    # Panel layout
    domain_col_w = config.domain_column_width if config.has_domain_column else 0
    panel_top = 2 if config.has_domain_column else 1
    panel_h = max(0, h - panel_top - 1)
    if panel_h < 10:
        return selected_idx

    # Left/right split
    if config.mode == "micro":
        left_min_w = _adaptive_left_min_width(
            w,
            base_min=_MARKET_MICRO_LEFT_BASE_MIN_WIDTH,
            floor_min=_MARKET_MICRO_LEFT_FLOOR_MIN_WIDTH,
            min_ratio=_MARKET_MICRO_LEFT_MIN_RATIO,
        )
        split_x = max(left_min_w, int(w * config.left_ratio))
        if split_x >= w - config.right_min_width:
            split_x = max(left_min_w, w - config.right_min_width)
        left_w = max(left_min_w, split_x)
    else:
        split_x = max(config.left_min_width, int(w * config.left_ratio))
        if split_x >= w - config.right_min_width - domain_col_w:
            split_x = max(24, w - config.right_min_width - domain_col_w)
        left_w = max(24, split_x - domain_col_w)

    right_x = min(w - 1, split_x + domain_col_w + 1)
    right_w = max(18, w - right_x)

    # Dynamic split: when signals are empty, give more space to the chart
    has_signals = bool(selected_rows)
    if has_signals:
        effective_top_ratio = config.right_top_ratio
    else:
        # No signals: chart gets ~85% of right panel, minimal bottom
        effective_top_ratio = min(0.85, config.right_top_ratio + 0.20)
    right_top_h = int(round(panel_h * effective_top_ratio))
    right_top_h = max(8, min(right_top_h, panel_h - 5))
    right_bottom_y = panel_top + right_top_h
    right_bottom_h = panel_h - right_top_h
    if right_bottom_h < 5:
        return selected_idx

    # Draw boxes
    box_attr = curses.color_pair(colors.get("SRC", 0))
    if config.has_domain_column:
        _draw_box(stdscr, 0, panel_top, domain_col_w, panel_h, box_attr)
        _draw_box(stdscr, domain_col_w, panel_top, left_w, panel_h, box_attr)
    else:
        _draw_box(stdscr, 0, panel_top, left_w, panel_h, box_attr)
    _draw_box(stdscr, right_x, panel_top, right_w, right_top_h, box_attr)
    _draw_box(stdscr, right_x, right_bottom_y, right_w, right_bottom_h, box_attr)

    # Domain column (fund mode)
    if config.has_domain_column and domain_keys:
        _safe_addstr(stdscr, panel_top, 1, _truncate("领域", domain_col_w - 2), curses.A_REVERSE | curses.A_BOLD)
        for i, dkey in enumerate(domain_keys):
            y = panel_top + 1 + i
            if y >= panel_top + panel_h - 1:
                break
            dlabel = get_domain_label(dkey)
            is_sel = dkey == selected_domain_key
            display = _truncate(dlabel, domain_col_w - 2)
            if is_sel:
                _safe_addstr(stdscr, y, 1, display, curses.A_REVERSE | curses.color_pair(colors.get("HIGHLIGHT", 0)))
            else:
                _safe_addstr(stdscr, y, 1, display)

    # Left panel table
    left_inner_w = max(0, left_w - 2)
    left_x_offset = domain_col_w + 1 if config.has_domain_column else 1
    _safe_addstr(stdscr, panel_top, left_x_offset + 1, _truncate(f"候选池({len(symbols)})", max(0, left_w - 4)), curses.A_REVERSE | curses.A_BOLD)

    resolved_cols = _resolve_columns(config.column_tiers, left_inner_w)
    render_left_row = _make_render_row(resolved_cols, left_inner_w)

    header_values = {key: header for key, header, _, _ in resolved_cols}
    _safe_addstr(stdscr, panel_top + 1, left_x_offset, render_left_row(" ", header_values), curses.A_REVERSE)

    # Scroll
    left_body_top = panel_top + 2
    left_body_h = max(0, panel_h - 3)
    if pane:
        pane.left_scroll = min(max(0, pane.left_scroll), max(0, len(symbols) - 1))
        if selected_idx < pane.left_scroll:
            pane.left_scroll = selected_idx
        if selected_idx >= pane.left_scroll + max(1, left_body_h):
            pane.left_scroll = max(0, selected_idx - max(1, left_body_h) + 1)
        left_scroll = pane.left_scroll
    else:
        left_scroll = 0
        if selected_idx >= max(1, left_body_h):
            left_scroll = selected_idx - max(1, left_body_h) + 1

    now_dt = datetime.now()
    left_visible = symbols[left_scroll : left_scroll + max(1, left_body_h)]

    # Build rank maps for fund mode
    if config.mode == "fund" and candidate_rank_map is None:
        candidate_rank_map = {sym: idx + 1 for idx, sym in enumerate(symbols)}

    for i, sym in enumerate(left_visible):
        y = left_body_top + i
        global_idx = left_scroll + i
        st = quote_state.entries.get(sym) or QuoteEntryState(quote=None, last_error="pending", last_fetch_at=0.0)
        q = st.quote
        name = _display_name(sym, q, config.market)
        code = _display_symbol(sym, config.market)
        prefix = ">" if global_idx == selected_idx else " "

        last_txt = "--"
        pct_txt = "--"
        if q is not None:
            chg = q.price - q.prev_close
            pct = (chg / q.prev_close * 100.0) if q.prev_close else 0.0
            last_txt = f"{q.price:.2f}"
            pct_txt = f"{pct:+.2f}%"

        if config.mode == "quad" or config.mode == "micro":
            symbol_rows = _signals_for_symbol(rows, sym, config.market)
            row_values = {
                "idx": str(global_idx + 1),
                "code": code,
                "name": name,
                "last": last_txt,
                "pct": pct_txt,
                "sig": str(_count_recent_signal_rows(symbol_rows, now_dt, max_age_s=12 * 60 * 60)),
            }
        else:  # fund
            cand_rank = candidate_rank_map.get(sym) if candidate_rank_map else None
            rank = model_rank_map.get(sym) if model_rank_map else None
            item = model_item_map.get(sym) if model_item_map else None
            row_values = {
                "cand": str(cand_rank) if cand_rank is not None else "--",
                "code": code,
                "name": name,
                "last": last_txt,
                "pct": pct_txt,
                "rank": f"#{rank}" if rank is not None else "--",
                "score": f"{item.total_score:.1f}" if item is not None else "--",
            }
        _safe_addstr(stdscr, y, left_x_offset, render_left_row(prefix, row_values))

    # Right top: label + stats + chart
    selected_label = _display_name(selected_symbol, selected_quote, config.market)
    selected_disp_symbol = _display_symbol(selected_symbol, config.market)
    detail_label = "票详情" if config.mode == "fund" else "标的详情"
    _safe_addstr(
        stdscr,
        panel_top,
        right_x + 2,
        _truncate(f"{detail_label}: {selected_label} ({selected_disp_symbol})", max(0, right_w - 4)),
        curses.A_UNDERLINE,
    )

    # Stats line
    if config.stats_mode == "fund":
        stats_line = _render_stats_fund(selected_quote, selected_state, selected_curve)
    elif config.stats_mode == "micro":
        stats_line = _render_stats_micro(selected_quote, selected_state, micro_snapshot)
    else:
        stats_line = _render_stats_standard(selected_quote, selected_state, selected_curve)
    _safe_addstr(stdscr, panel_top + 1, right_x + 1, _truncate(stats_line, max(0, right_w - 2)))

    # Price curve
    chart_y = panel_top + 2
    chart_h = max(1, right_top_h - 3)
    # Deferred import to avoid circular dependency (tui.py imports from draw_market)
    from .tui import _draw_price_curve
    _draw_price_curve(
        stdscr,
        selected_curve,
        colors,
        right_x + 1,
        chart_y,
        right_w - 2,
        chart_h,
        marker_rows=selected_rows,
    )

    # Right bottom
    if config.right_bottom_mode == "signals":
        signal_panel_title = _build_recent_signal_panel_title(selected_rows, now_dt)
        _safe_addstr(stdscr, right_bottom_y, right_x + 2, _truncate(signal_panel_title, max(0, right_w - 4)), curses.A_UNDERLINE)
        _render_right_bottom_signals(
            stdscr,
            selected_rows,
            now_dt,
            colors,
            right_x + 1,
            right_bottom_y + 1,
            max(0, right_w - 2),
            max(0, right_bottom_h - 2),
        )
    elif config.right_bottom_mode == "details":
        _render_right_bottom_details(
            stdscr,
            selected_symbol,
            selected_quote,
            selected_rows,
            quote_state,
            domain_top_symbols,
            domain_label,
            model_rank_map or {},
            model_item_map or {},
            candidate_rank_map or {},
            top_n_limit,
            ranking_snapshot,
            now_dt,
            right_x,
            right_bottom_y,
            right_w,
            right_bottom_h,
            config.market,
        )

    # ─── Visual separators ───
    # Vertical separator between left and right panels (plain ASCII for compatibility)
    for vy in range(panel_top, h - 1):
        _safe_addstr(stdscr, vy, split_x, "|")
    # Horizontal separator between chart (top-right) and signals/details (bottom-right)
    _safe_addstr(stdscr, right_bottom_y, right_x, "-" * max(0, min(w - right_x, right_w)))

    return selected_idx
