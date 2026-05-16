"""Market page module — multi-market quad layout, price curves, and TUI rendering."""

from __future__ import annotations

import collections
import locale
import curses
import math
import os
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from tradecat.common.utils.scheduler import wait_seconds
from tradecat.tui.micro import Candle, MicroConfig, MicroEngine, MicroSnapshot
from tradecat.tui.quote import Quote, fetch_daily_curve_1d, fetch_intraday_curve_1m, fetch_quote, fetch_quotes
from tradecat.tui.draw_market import (
    MarketPanelConfig,
    draw_market_panel,
    quad_config as _quad_config,
    fund_config as _fund_config,
    micro_config as _micro_config,
)
from tradecat.tui.etf_profiles import (
    get_all_domain_keys,
    get_domain_label,
    get_etf_domain_profile,
    load_dynamic_auto_driving_symbols,
)
from tradecat.tui.etf_selector import select_etf_candidates
from tradecat.tui.fund_bridge import DirectFundBridge, seed_curve_from_daily_candles
from tradecat.tui.fund_symbols import (
    match_cn_fund_signal as _match_cn_fund_signal_shared,
    normalize_cn_fund_symbol as _normalize_cn_fund_symbol_shared,
)
from tradecat.tui.db import SignalRow, fetch_recent, parse_ts, probe
from tradecat.tui.watchlists import (
    Watchlists,
    normalize_cn_fund_symbols,
    normalize_cn_symbols,
    normalize_crypto_symbols,
    normalize_hk_symbols,
    normalize_metals_symbols,
    normalize_us_symbols,
    save_watchlists,
)

# Utility helpers
def _safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    try:
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x < 0: return
        available = max_x - x
        if available <= 0: return
        win.addnstr(y, x, s, available, attr)
    except curses.error: pass

def _truncate(s: str, width: int) -> str:
    if width <= 0: return ""
    result = []
    current_width = 0
    for ch in s:
        ch_width = 2 if ord(ch) > 0x7F else 1
        if current_width + ch_width > width: break
        result.append(ch)
        current_width += ch_width
    return "".join(result)

def _char_display_width(ch: str) -> int:
    if len(ch) != 1: return 0
    cp = ord(ch)
    if cp <= 0x7F: return 1
    if (0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F or
            0xFF00 <= cp <= 0xFFEF or 0x3400 <= cp <= 0x4DBF): return 2
    return 1

def _text_display_width(text: str) -> int:
    return sum(_char_display_width(ch) for ch in text)

def _fit_cell(text: str, width: int, *, align: str = "left") -> str:
    tw = _text_display_width(text)
    if tw >= width: return _truncate(text, width)
    pad = width - tw
    if align == "right": return " " * pad + text
    if align == "center": return " " * (pad // 2) + text + " " * (pad - pad // 2)
    return text + " " * pad

def _safe_vline(win, y: int, x: int, height: int, attr: int = 0) -> None:
    try: win.vline(y, x, attr, height)
    except curses.error: pass

def _safe_hline(win, y: int, x: int, width: int, attr: int = 0) -> None:
    try: win.hline(y, x, attr, width)
    except curses.error: pass

def _draw_box(win, x: int, y: int, width: int, height: int, attr: int = 0) -> None:
    _safe_hline(win, y, x, width, attr)
    _safe_hline(win, y + height - 1, x, width, attr)
    _safe_vline(win, y, x, height, attr)
    _safe_vline(win, y, x + width - 1, height, attr)

# === _fmt_vol ===


# Import constants and helpers from tui.py
from tradecat.tui._helpers import (
    _adaptive_left_min_width, _build_recent_signal_panel_title,
    _count_recent_signal_rows, _crypto_signal_symbol_to_pair,
    _display_name, _display_symbol, _draw_box, _safe_addstr, _safe_hline, _safe_vline,
    _fmt_freshness, _fmt_duration_compact, _fmt_quote_ts, _fmt_quote_ts_date8, _fmt_signed, _fmt_time, _fmt_vol,
    _format_service_status_bar, _is_finite_number, _market_display_name,
    _safe_int, _signals_for_symbol, _split_signal_rows_by_age, _view_display_name,
    _signal_row_age_seconds, _latest_signal_row, _window_signal_stats,
    _char_display_width, _text_display_width, _truncate, _fit_cell, _line_chars,
    _coerce_float, _coerce_int, _coerce_pct, _extract_metric, _resample_series,
)
# Market-specific constants (defined in tui.py, needed here)
from tradecat.tui._helpers import (
    _CLOSED_CURVE_HISTORY_LIMIT, _CLOSED_CURVE_RETRY_SECONDS,
    _CLOSED_CURVE_STALE_SECONDS, _CLOSED_CURVE_TARGET_SPAN_SECONDS,
    _FUND_CN_CURVE_DAYS, _FUND_CN_CURVE_REFRESH_SECONDS,
    _MARKET_MICRO_LEFT_BASE_MIN_WIDTH, _MARKET_MICRO_LEFT_FLOOR_MIN_WIDTH,
    _MARKET_MICRO_LEFT_MIN_RATIO, _MARKET_MICRO_LEFT_RATIO,
    _MARKET_MICRO_RIGHT_MIN_WIDTH,
    _MARKET_TABS, _MARKET_TAB_LABELS, _PAGE_NEWS_VIEW,
)
# Lazy imports to avoid circular dependency
_draw_market_backtest = None
_draw_market_news = None
def _lazy_imports():
    global _draw_market_backtest, _draw_market_news
    if _draw_market_backtest is None:
        from tradecat.tui.pages.backtest import _draw_market_backtest as bt
        from tradecat.tui.pages.news import _draw_market_news as nw
        _draw_market_backtest = bt
        _draw_market_news = nw

def _fmt_vol(v: float) -> str:
    if v <= 0:
        return "--"
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v/1_000:.2f}K"
    return f"{v:.0f}"



# === _display_symbol ===

def _display_symbol(sym: str, market: str) -> str:
    symbol = (sym or "").strip().upper()
    if market == "hk_stock":
        return f"{symbol}.HK"
    if market == "cn_stock" and len(symbol) > 2 and symbol[:2] in {"SH", "SZ"}:
        return f"{symbol[2:]}.{symbol[:2]}"
    if market == "cn_fund":
        if len(symbol) > 2 and symbol[:2] in {"SH", "SZ"}:
            return f"{symbol[2:]}.{symbol[:2]}"
        if symbol.isdigit() and len(symbol) == 6:
            return symbol
    if market == "crypto_spot" and "_" in symbol:
        return symbol.replace("_", "/")
    if market in {"metals", "metals_spot"} and symbol.endswith("USD") and len(symbol) >= 6:
        return f"{symbol[:3]}/USD"
    return symbol



# === _display_name ===

def _display_name(sym: str, q: Quote | None, market: str) -> str:
    if q is not None:
        name = (q.name or "").strip().replace("\n", " ")
        if name:
            return name
    return _display_symbol(sym, market)



# === _build_header_line ===

def _build_header_line(now: str, view: str, status: str, svc: str, width: int) -> str:
    view_txt = _view_display_name(view)
    left = f"TradeCat TUI  |  {now}  |  页面={view_txt}  |  {status}"
    left_compact = f"TUI {now} 页={view_txt} {status}"
    svc_txt = (svc or "").strip()
    if not svc_txt:
        return _truncate(left, width)

    sep = "  |  "
    full = f"{left}{sep}{svc_txt}"
    if len(full) <= width:
        return full

    # Keep service status visible on narrow terminals; shrink left context first.
    left_budget = width - len(sep) - len(svc_txt)
    if left_budget >= 12:
        if len(left_compact) <= left_budget:
            return f"{left_compact}{sep}{svc_txt}"
        return f"{_truncate(left_compact, left_budget)}{sep}{svc_txt}"

    # Very narrow terminals: show compact service text only.
    return _truncate(svc_txt, width)



# === _draw_view_panel_to_end ===

def _draw_view_panel(
    win,
    db_path: str,
    rows: list[SignalRow],
    rows_all: list[SignalRow],
    filt: Filters,
    scroll: int,
    colors: dict[str, int],
    refresh_s: float,
    last_id: int,
    quote_cfgs: QuoteConfigs,
    quote_state_us: QuoteBookState,
    quote_state_hk: QuoteBookState,
    quote_state_cn: QuoteBookState,
    quote_state_fund_cn: QuoteBookState,
    quote_state_crypto: QuoteBookState,
    quote_state_metals: QuoteBookState,
    latest_sig_map_crypto: dict[str, SignalRow],
    us_curve_map: dict[str, list[Candle]],
    hk_curve_map: dict[str, list[Candle]],
    cn_curve_map: dict[str, list[Candle]],
    fund_cn_curve_map: dict[str, list[Candle]],
    fund_cn_daily_curve_map: dict[str, list[Candle]],
    crypto_curve_map: dict[str, list[Candle]],
    us_micro_snapshots: dict[str, MicroSnapshot],
    hk_micro_snapshots: dict[str, MicroSnapshot],
    cn_micro_snapshots: dict[str, MicroSnapshot],
    fund_cn_micro_snapshots: dict[str, MicroSnapshot],
    micro_snapshot: MicroSnapshot,
    micro_symbols: list[str],
    view: str,
    qscroll: int,
    master_pane: MasterPaneState | None,
    runtime_state: RuntimeState,
    news_state: NewsPageState | None = None,
    news_snapshot: NewsFeedSnapshot | None = None,
) -> None:
    h, w = win.getmaxyx()
    if view == "quotes_us":
        _draw_quotes(win, "US", quote_cfgs.us, quote_state_us, w, h, qscroll)
    elif view == "market_us":
        _cfg = _quad_config("US")
        _syms = [s.strip().upper() for s in (quote_cfgs.us.symbols or []) if (s or "").strip()]
        _pane = master_pane or MasterPaneState()
        draw_market_panel(
            win, _cfg, _syms, _pane.selected, quote_state_us, rows_all,
            colors, us_curve_map, w, h, pane=_pane, refresh_s=refresh_s,
        )
    elif view == "market_hk":
        _cfg = _quad_config("HK")
        _syms = [s.strip().upper() for s in (quote_cfgs.hk.symbols or []) if (s or "").strip()]
        _pane = master_pane or MasterPaneState()
        draw_market_panel(
            win, _cfg, _syms, _pane.selected, quote_state_hk, rows_all,
            colors, hk_curve_map, w, h, pane=_pane, refresh_s=refresh_s,
        )
    elif view == "quotes_hk":
        _draw_quotes(win, "HK", quote_cfgs.hk, quote_state_hk, w, h, qscroll)
    elif view == "quotes_cn":
        _draw_quotes(win, "CN", quote_cfgs.cn, quote_state_cn, w, h, qscroll)
    elif view == "market_cn":
        _cfg = _quad_config("CN")
        _syms = [s.strip().upper() for s in (quote_cfgs.cn.symbols or []) if (s or "").strip()]
        _pane = master_pane or MasterPaneState()
        draw_market_panel(
            win, _cfg, _syms, _pane.selected, quote_state_cn, rows_all,
            colors, cn_curve_map, w, h, pane=_pane, refresh_s=refresh_s,
        )
    elif view == "market_fund_cn":
        _cfg = _fund_config()
        _syms = [s.strip().upper() for s in (quote_cfgs.fund_cn.symbols or []) if (s or "").strip()]
        _pane = master_pane or MasterPaneState()
        _rs = runtime_state
        _fd = _rs.fund_domain
        _dp = get_etf_domain_profile(_fd.selected_key)
        _dl = _dp.label or _fd.selected_key
        _top_n = max(1, int(_dp.top_n))
        _ranking = replace(_dp, top_n=max(_top_n, len(_syms)))
        _snap = select_etf_candidates(
            profile=_ranking, symbols=_syms, quote_entries=quote_state_fund_cn.entries,
            curve_map=fund_cn_curve_map, micro_snapshots=fund_cn_micro_snapshots,
            now_ts=time.time(), stale_seconds=120,
        )
        _items = tuple(_snap.items)
        _mr = {item.symbol: idx + 1 for idx, item in enumerate(_items)}
        _mi = {item.symbol: item for item in _items}
        _cr = {sym: idx + 1 for idx, sym in enumerate(_syms)}
        draw_market_panel(
            win, _cfg, _syms, _pane.selected, quote_state_fund_cn, rows_all,
            colors, fund_cn_curve_map, w, h,
            pane=_pane, domain_keys=_fd.keys, selected_domain_key=_fd.selected_key,
            daily_curve_map=fund_cn_daily_curve_map,
            ranking_snapshot=_snap, model_rank_map=_mr, model_item_map=_mi,
            domain_top_symbols=tuple(_syms[:_top_n]), top_n_limit=_top_n,
            domain_label=_dl, candidate_rank_map=_cr, refresh_s=refresh_s,
        )
    elif view in {"quotes_crypto", "market_crypto", "market_micro"}:
        _cfg = _micro_config()
        _syms = [s.strip().upper() for s in (micro_symbols or []) if (s or "").strip()]
        _focus = (micro_snapshot.symbol or "").strip().upper()
        if _focus and _focus not in _syms:
            _syms.insert(0, _focus)
        _sel = _syms.index(_focus) if _focus in _syms else 0
        draw_market_panel(
            win, _cfg, _syms, _sel, quote_state_crypto, rows_all,
            colors, crypto_curve_map, w, h, micro_snapshot=micro_snapshot,
        )
    elif view == "market_backtest":
        _draw_market_backtest(win, colors, w, h)
    elif view == "market_news":
        _draw_market_news(
            win,
            news_state or NewsPageState(),
            news_snapshot,
            quote_cfgs,
            quote_state_us,
            quote_state_hk,
            quote_state_cn,
            quote_state_crypto,
            colors,
            w,
            h,
        )
    elif view == "quotes_metals":
        _draw_quotes(win, "METALS", quote_cfgs.metals, quote_state_metals, w, h, qscroll)
    else:
        _draw_signals(win, db_path, rows, filt, scroll, colors, refresh_s, last_id, w, h, quote_state_crypto)


def _draw_paper_trading_page(stdscr, h: int, w: int, colors: dict[str, int]) -> None:
    """P2 模拟盘页面：显示账户、持仓、订单。"""
    try:
        from tradecat.core.paper_trading.engine import PaperTradingEngine
        from tradecat.core.paper_trading.repository import SqliteRepository

        repo = SqliteRepository()
        engine = PaperTradingEngine(repo)
        accounts = engine.list_accounts()
    except Exception:
        accounts = []

    y = 2
    if not accounts:
        _safe_addstr(stdscr, y, 2, "暂无模拟盘账户", curses.A_BOLD)
        _safe_addstr(stdscr, y + 2, 2, "使用 tradecat paper create <名称> 创建账户")
        return

    for acct in accounts:
        if y + 8 > h:
            break
        status = engine.status(acct.account_id)
        balance = status.get("account", acct).balance if status.get("account") else acct.balance
        equity = status.get("total_equity", balance)
        positions = status.get("positions", [])
        orders = status.get("recent_orders", [])
        drawdown = status.get("drawdown_pct", 0)

        header = f"账户: {acct.name}  余额: {balance}  权益: {equity}  杠杆: {acct.leverage}x  回撤: {drawdown}%"
        _safe_addstr(stdscr, y, 2, _truncate(header, w - 4), curses.A_BOLD)
        y += 1

        # 持仓
        if positions:
            _safe_addstr(stdscr, y, 2, "持仓:", curses.A_UNDERLINE)
            y += 1
            pos_header = "  方向  标的        数量       开仓价     盈亏"
            _safe_addstr(stdscr, y, 2, _truncate(pos_header, w - 4))
            y += 1
            for pos in positions[:10]:
                side = pos.side.value if hasattr(pos.side, 'value') else str(pos.side)
                sym = pos.symbol
                qty = str(pos.qty)
                entry = str(pos.entry_price)
                pnl = pos.unrealized_pnl
                pnl_str = f"+{pnl}" if pnl >= 0 else str(pnl)
                line = f"  {side:5s} {sym:10s} {qty:>10s} {entry:>10s} {pnl_str:>10s}"
                attr = curses.color_pair(colors.get("BUY", 0)) if pnl >= 0 else curses.color_pair(colors.get("SELL", 0))
                _safe_addstr(stdscr, y, 2, _truncate(line, w - 4), attr)
                y += 1
        else:
            _safe_addstr(stdscr, y, 2, "持仓: 无")
            y += 1

        # 最近订单
        if orders:
            _safe_addstr(stdscr, y, 2, "最近订单:", curses.A_UNDERLINE)
            y += 1
            for order in orders[:5]:
                side = order.side.value if hasattr(order.side, 'value') else str(order.side)
                sym = order.symbol
                qty = str(order.qty)
                price = str(order.entry_price)
                st = order.status.value if hasattr(order.status, 'value') else str(order.status)
                line = f"  {side:5s} {sym:10s} {qty:>10s} @ {price:>10s}  [{st}]"
                _safe_addstr(stdscr, y, 2, _truncate(line, w - 4))
                y += 1
        y += 1


def _draw(
    stdscr,
    db_path: str,
    rows: list[SignalRow],
    rows_all: list[SignalRow],
    filt: Filters,
    scroll: int,
    colors: dict[str, int],
    refresh_s: float,
    last_id: int,
    quote_cfgs: QuoteConfigs,
    quote_state_us: QuoteBookState,
    quote_state_hk: QuoteBookState,
    quote_state_cn: QuoteBookState,
    quote_state_fund_cn: QuoteBookState,
    quote_state_crypto: QuoteBookState,
    quote_state_metals: QuoteBookState,
    latest_sig_map_crypto: dict[str, SignalRow],
    us_curve_map: dict[str, list[Candle]],
    hk_curve_map: dict[str, list[Candle]],
    cn_curve_map: dict[str, list[Candle]],
    fund_cn_curve_map: dict[str, list[Candle]],
    fund_cn_daily_curve_map: dict[str, list[Candle]],
    crypto_curve_map: dict[str, list[Candle]],
    us_micro_snapshots: dict[str, MicroSnapshot],
    hk_micro_snapshots: dict[str, MicroSnapshot],
    cn_micro_snapshots: dict[str, MicroSnapshot],
    fund_cn_micro_snapshots: dict[str, MicroSnapshot],
    micro_snapshot: MicroSnapshot,
    micro_symbols: list[str],
    service_status: ServiceStatus,
    view: str,
    qscroll: int,
    master_pane: MasterPaneState | None,
    runtime_state: RuntimeState,
    news_state: NewsPageState | None = None,
    news_snapshot: NewsFeedSnapshot | None = None,
    top_page: int = 1,
    market_tab: int = 0,
) -> None:
    # --- P2 模拟盘页面 ---
    if top_page == 2:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _draw_header(stdscr, colors, filt, refresh_s, view, service_status, w, top_page, market_tab)
        _draw_paper_trading_page(stdscr, h, w, colors)
    else:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _draw_header(stdscr, colors, filt, refresh_s, view, service_status, w, top_page, market_tab)
        _draw_view_panel(
            stdscr,
            db_path,
            rows,
            rows_all,
            filt,
            scroll,
            colors,
            refresh_s,
            last_id,
            quote_cfgs,
            quote_state_us,
            quote_state_hk,
            quote_state_cn,
            quote_state_fund_cn,
            quote_state_crypto,
            quote_state_metals,
            latest_sig_map_crypto,
            us_curve_map,
            hk_curve_map,
            cn_curve_map,
            fund_cn_curve_map,
            fund_cn_daily_curve_map,
            crypto_curve_map,
            us_micro_snapshots,
            hk_micro_snapshots,
            cn_micro_snapshots,
            fund_cn_micro_snapshots,
            micro_snapshot,
            micro_symbols,
            view,
            qscroll,
            master_pane,
            runtime_state,
            news_state,
            news_snapshot,
        )

    stdscr.noutrefresh()
    curses.doupdate()

def _draw_header(
    stdscr,
    colors: dict[str, int],
    filt: Filters,
    refresh_s: float,
    view: str,
    service_status: ServiceStatus,
    width: int,
    top_page: int = 1,
    market_tab: int = 0,
) -> None:
    now = datetime.now().strftime("%y-%m-%d %H:%M:%S")
    status = "已暂停" if filt.paused else f"刷新={refresh_s:.1f}s"
    svc = _format_service_status_bar(service_status)
    header = _build_header_line(now, view, status, svc, width)
    stdscr.move(0, 0)
    stdscr.clrtoeol()
    _safe_addstr(stdscr, 0, 0, header, curses.color_pair(colors.get("ALERT", 0)) | curses.A_BOLD)
    # --- 三页 tab 栏 ---
    pages = [("1:行情", 1), ("2:模拟盘", 2), ("3:资讯", 3)]
    tab_line = "  ".join(
        f"[{label}]" if tp == top_page else f" {label} " for label, tp in pages
    )
    if top_page == 1:
        sub_tabs = _MARKET_TAB_LABELS
        sub_line = "  ".join(
            f"<{lbl}>" if i == market_tab else f" {lbl} " for i, lbl in enumerate(sub_tabs)
        )
        tab_line += "  " + sub_line
    stdscr.move(1, 0)
    stdscr.clrtoeol()
    _safe_addstr(stdscr, 1, 0, _truncate(tab_line, width), curses.A_BOLD)


def _draw_market_master(
    stdscr,
    label: str,
    quote_cfg: QuoteConfig,
    quote_state: QuoteBookState,
    rows: list[SignalRow],
    pane: MasterPaneState,
    w: int,
    h: int,
    refresh_s: float,
    show_signals: bool = True,
) -> None:
    key_hint = (
        "按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 5基金 | 6港股 | 7资讯 | Tab切Agent | +/-加减自选 | ↑↓滚动"
        if show_signals
        else "按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 5基金 | 6港股 | 7资讯 | +/-加减自选 | ↑↓滚动"
    )

    symbols = [s.strip().upper() for s in (quote_cfg.symbols or []) if (s or "").strip()]
    if not (quote_cfg.enabled and symbols):
        _safe_addstr(stdscr, 1, 0, _truncate("行情页：未启用或无标的", w))
        _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))
        return

    pane.selected = min(max(0, pane.selected), max(0, len(symbols) - 1))
    selected_symbol = symbols[pane.selected]
    selected_rows = _signals_for_symbol(rows, selected_symbol, quote_cfg.market)

    market_name = _market_display_name(quote_cfg.market, label)
    line1 = f"行情[{market_name}]"
    _safe_addstr(stdscr, 1, 0, _truncate(line1, w))
    _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))

    if not show_signals:
        pane.focus = "left"

    if show_signals:
        split_x = max(42, int(w * 0.72))
        if split_x >= w - 24:
            split_x = max(28, w - 24)
        left_w = max(24, split_x)
        right_x = min(w - 1, split_x + 1)
        right_w = max(10, w - right_x)
    else:
        left_w = max(24, w)
        right_x = w
        right_w = 0

    panel_top = 2
    panel_h = max(0, h - panel_top - 1)
    if panel_h < 4:
        return

    _draw_box(stdscr, 0, panel_top, left_w, panel_h)
    if show_signals:
        _draw_box(stdscr, right_x, panel_top, right_w, panel_h)

    left_focus = "*" if (pane.focus == "left" or not show_signals) else " "
    sel_state = quote_state.entries.get(selected_symbol)
    sel_quote = sel_state.quote if sel_state else None
    _safe_addstr(stdscr, panel_top, 1, _truncate(f"[{left_focus}] 行情", left_w - 2), curses.A_UNDERLINE)
    if show_signals:
        right_focus = "*" if pane.focus == "right" else " "
        _safe_addstr(
            stdscr,
            panel_top,
            right_x + 1,
            _truncate(f"[{right_focus}] 信号: {_display_name(selected_symbol, sel_quote, quote_cfg.market)}", right_w - 2),
            curses.A_UNDERLINE,
        )

    left_col = "名称         最新     涨跌     幅度     开盘     最高     最低      量      时间      延迟 状态"
    _safe_addstr(stdscr, panel_top + 1, 1, _truncate(left_col, left_w - 2), curses.A_UNDERLINE)
    if show_signals:
        right_col = "时间    方向 强度 周期 类型"
        _safe_addstr(stdscr, panel_top + 1, right_x + 1, _truncate(right_col, right_w - 2), curses.A_UNDERLINE)

    left_body_top = panel_top + 2
    right_body_top = panel_top + 2
    left_body_h = max(0, panel_h - 3)
    right_body_h = max(0, panel_h - 3) if show_signals else 0

    pane.left_scroll = min(max(0, pane.left_scroll), max(0, len(symbols) - 1))
    if pane.selected < pane.left_scroll:
        pane.left_scroll = pane.selected
    if pane.selected >= pane.left_scroll + max(1, left_body_h):
        pane.left_scroll = max(0, pane.selected - max(1, left_body_h) + 1)

    now_dt = datetime.now()
    left_visible = symbols[pane.left_scroll : pane.left_scroll + max(1, left_body_h)]
    now_dt = datetime.now()
    for i, sym in enumerate(left_visible):
        y = left_body_top + i
        st = quote_state.entries.get(sym) or QuoteEntryState(quote=None, last_error="pending", last_fetch_at=0.0)
        q = st.quote
        age_s = int(max(0.0, time.time() - (st.last_fetch_at or 0.0))) if st.last_fetch_at else 0
        prefix = ">" if (pane.left_scroll + i) == pane.selected else " "
        name = _display_name(sym, q, quote_cfg.market)
        if q is None:
            status = (st.last_error or "no-data").strip()[:2]
            line = f"{prefix} {name:<10} {'--':>7} {'--':>8} {'--':>7} {'--':>7} {'--':>7} {'--':>7} {'--':>8} {'--':<8} {age_s:>3}s {status:<2}"
            _safe_addstr(stdscr, y, 1, _truncate(line, left_w - 2))
            continue
        chg = q.price - q.prev_close
        pct = (chg / q.prev_close * 100.0) if q.prev_close else 0.0
        status = "ok" if not (st.last_error or "").strip() else "er"
        line = (
            f"{prefix} {name:<10} {q.price:>7.2f} {chg:>+8.2f} {pct:>+6.2f}% {q.open:>7.2f} {q.high:>7.2f} {q.low:>7.2f} "
            f"{_fmt_vol(q.volume):>8} {_fmt_quote_ts_date8(q.ts):<8} {age_s:>3}s {status:<2}"
        )
        _safe_addstr(stdscr, y, 1, _truncate(line, left_w - 2))

    if show_signals:
        if pane.right_scroll >= 10**8:
            right_start = max(0, len(selected_rows) - max(1, right_body_h))
        else:
            right_start = min(max(0, pane.right_scroll), max(0, len(selected_rows) - 1))
        right_visible = selected_rows[right_start : right_start + max(1, right_body_h)]

        for i, row in enumerate(right_visible):
            y = right_body_top + i
            t = _fmt_time(row.timestamp)
            direction = (row.direction or "").upper()[:4]
            strength = str(row.strength)[:3]
            tf = (row.timeframe or "")[:3]
            stype = (row.signal_type or "")[:10]
            line = f"{t:<8}{direction:<5}{strength:>3} {tf:<3} {stype:<10}"
            _safe_addstr(stdscr, y, right_x + 1, _truncate(line, right_w - 2))

def _draw_quotes(
    stdscr,
    label: str,
    quote_cfg: QuoteConfig,
    quote_state: QuoteBookState,
    w: int,
    h: int,
    qscroll: int,
    sig_map: dict[str, SignalRow] | None = None,
) -> None:
    key_hint = "按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 5基金 | 6港股 | 7资讯 | +/-加减自选 | ↑↓滚动 | r刷新"

    symbols = [s.strip().upper() for s in (quote_cfg.symbols or []) if (s or "").strip()]
    if not (quote_cfg.enabled and symbols):
        _safe_addstr(stdscr, 1, 0, _truncate("报价页：未启用或无标的", w))
        _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))
        return

    # Summary lines
    market_name = _market_display_name(quote_cfg.market, label)
    line1 = f"报价[{market_name}]"
    _safe_addstr(stdscr, 1, 0, _truncate(line1, w))
    _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))

    # Table header
    col = "代码        名称         最新     涨跌     幅度     开盘     最高     最低      量      币种  时间               延迟 状态"
    if quote_cfg.market == "crypto_spot":
        col += "  信号向 强度 周期 信号旧度 信号类型"
    _safe_addstr(stdscr, 3, 0, _truncate(col, w), curses.A_UNDERLINE)

    body_top = 4
    body_h = max(0, h - body_top - 1)
    if body_h <= 0:
        return

    # Stable symbol order.
    entries: list[tuple[str, QuoteEntryState]] = []
    for sym in symbols:
        st = quote_state.entries.get(sym) or QuoteEntryState(quote=None, last_error="pending", last_fetch_at=0.0)
        entries.append((sym, st))

    if qscroll >= 10**8:
        start = max(0, len(entries) - body_h)
    else:
        start = min(max(0, qscroll), max(0, len(entries) - 1))
    visible = entries[start : start + body_h]

    for i, (sym, st) in enumerate(visible):
        y = body_top + i
        q = st.quote
        age_s = max(0.0, time.time() - (st.last_fetch_at or 0.0)) if st.last_fetch_at else 0.0
        disp_sym = sym
        if quote_cfg.market == "hk_stock":
            disp_sym = f"{sym}.HK"
        elif quote_cfg.market == "cn_stock" and len(sym) > 2 and sym[:2] in {"SH", "SZ"}:
            disp_sym = f"{sym[2:]}.{sym[:2]}"
        elif quote_cfg.market == "crypto_spot" and "_" in sym:
            disp_sym = sym.replace("_", "/")
        elif quote_cfg.market in {"metals", "metals_spot"} and sym.endswith("USD") and len(sym) >= 6:
            # Common UX for metals FX-style tickers (XAUUSD -> XAU/USD).
            disp_sym = f"{sym[:3]}/USD"
        if q is None:
            status = (st.last_error or "unavailable").strip()
            line = (
                f"{disp_sym:<10}  {'--':<10}  {'--':>7}  {'--':>7}  {'--':>7}  {'--':>7}  {'--':>7}  {'--':>7}  "
                f"{'--':>7}  {'--':<4}  {'--':<17}  {age_s:>3.0f}s  {status}"
            )
            _safe_addstr(stdscr, y, 0, _truncate(line, w))
            continue

        chg = q.price - q.prev_close
        pct = (chg / q.prev_close * 100.0) if q.prev_close else 0.0
        vol = _fmt_vol(q.volume)
        cur_raw = (q.currency or "--").strip()
        cur = cur_raw[:4] if quote_cfg.market == "crypto_spot" else cur_raw[:3]
        # Name can be non-ASCII; keep it short to reduce width issues.
        name = (q.name or "").strip().replace("\n", " ")
        if not name:
            name = "--"
        name = _truncate(name, 10)
        status = "ok" if not (st.last_error or "").strip() else (st.last_error or "").strip()
        if status == "ok" and (q.source or "").strip():
            status = f"ok({q.source})"
        line = (
            f"{disp_sym:<10}  {name:<10}  {q.price:>7.2f}  {chg:>+7.2f}  {pct:>+6.2f}%  {q.open:>7.2f}  {q.high:>7.2f}  {q.low:>7.2f}  "
            f"{vol:>7}  {cur:<4}  {_fmt_quote_ts(q.ts):<17}  {age_s:>3.0f}s  {status}"
        )
        if quote_cfg.market == "crypto_spot" and sig_map is not None:
            sig = sig_map.get(sym)
            if sig is None:
                line += "  --      --  --      --s  --"
            else:
                sig_dir = (sig.direction or "").upper()[:5] or "--"
                sig_str = f"{sig.strength:>3}" if sig.strength is not None else "--"
                sig_tf = (sig.timeframe or "")[:3] or "--"
                dt = parse_ts(sig.timestamp)
                sig_age = int(max(0.0, time.time() - dt.timestamp())) if dt != datetime.min else 0
                sig_type = (sig.signal_type or "")[:10] or "--"
                line += f"  {sig_dir:<5}  {sig_str:>3} {sig_tf:<3}  {sig_age:>6}s  {sig_type:<10}"
        _safe_addstr(stdscr, y, 0, _truncate(line, w))


def _draw_signals(
    stdscr,
    db_path: str,
    rows: list[SignalRow],
    filt: Filters,
    scroll: int,
    colors: dict[str, int],
    refresh_s: float,
    last_id: int,
    w: int,
    h: int,
    quote_state_crypto: QuoteBookState,
) -> None:
    # Quote hint (this view focuses on signals)
    status = "已暂停" if filt.paused else f"刷新={refresh_s:.1f}s"
    header2 = f"信号页: 行数={len(rows)} last_id={last_id}  |  {status}  |  按键: q退出, t切页"
    _safe_addstr(stdscr, 1, 0, _truncate(header2, w))

    src = ",".join(sorted(filt.sources)) or "无"
    dirs = ",".join(sorted(filt.directions)) or "无"
    line3 = f"数据库: {db_path}  |  来源: {src}  |  方向: {dirs}  |  空格暂停, 方向键滚动"
    _safe_addstr(stdscr, 2, 0, _truncate(line3, w))

    # Column header
    col = "时间     源    向   强度  标的          周期  价格         类型                消息"
    _safe_addstr(stdscr, 3, 0, _truncate(col, w), curses.A_UNDERLINE)

    body_top = 4
    body_h = max(0, h - body_top - 1)
    if body_h <= 0:
        return

    start = min(scroll, max(0, len(rows) - 1))
    visible = rows[start : start + body_h]

    for i, r in enumerate(visible):
        y = body_top + i
        t = _fmt_time(r.timestamp)
        src = (r.source or "").upper()
        direction = (r.direction or "").upper()
        strength = str(r.strength)
        symbol = r.symbol
        tf = r.timeframe or ""
        price = "" if r.price is None else f"{r.price:.4f}"
        stype = r.signal_type
        msg = (r.message or "").replace("\n", " ")
        # For crypto signals, append current quote info (if available) so the signals page aligns with quotes_crypto.
        pair = _crypto_signal_symbol_to_pair(r.symbol)
        if "_" in pair:
            st = quote_state_crypto.entries.get(pair)
            if st and st.quote is not None:
                q = st.quote
                q_age_s = int(max(0.0, time.time() - (st.last_fetch_at or 0.0))) if st.last_fetch_at else 0
                msg = f"{msg} | q={q.price:.2f} {q_age_s}s {q.source}"

        dir_attr = curses.color_pair(colors.get(direction, 0)) | curses.A_BOLD
        src_attr = curses.color_pair(colors.get("SRC", 0))

        x = 0
        _safe_addstr(stdscr, y, x, f"{t:<8}")
        x += 8
        _safe_addstr(stdscr, y, x, f"{src:<5}"[:5], src_attr)
        x += 6
        _safe_addstr(stdscr, y, x, f"{direction:<4}"[:4], dir_attr)
        x += 5
        _safe_addstr(stdscr, y, x, f"{strength:>3}"[:3])
        x += 5
        _safe_addstr(stdscr, y, x, _truncate(f"{symbol:<12}", 12))
        x += 13
        _safe_addstr(stdscr, y, x, _truncate(f"{tf:<4}", 4))
        x += 5
        _safe_addstr(stdscr, y, x, _truncate(f"{price:<11}", 11))
        x += 12
        _safe_addstr(stdscr, y, x, _truncate(f"{stype:<18}", 18))
        x += 19
        _safe_addstr(stdscr, y, x, _truncate(msg, max(0, w - x)))

    # Footer
    footer = (
        "筛选: p PG | s SQLITE | b BUY | e SELL | a ALERT | r刷新 | "
        "t主页面切换 | 1美股 | 2A股 | 3加密 | 5基金 | 6港股 | 7资讯"
    )
    _safe_addstr(stdscr, h - 1, 0, _truncate(footer, w))


def _fmt_signed(v: float) -> str:
    return f"{v:+.3f}"


def _sample_candles_minmax(candles: list[Candle], target_points: int) -> list[Candle]:
    """Downsample dense candles while preserving local extremes."""
    if target_points <= 0:
        return []
    if len(candles) <= target_points:
        return candles[-target_points:]
    if len(candles) <= 4 or target_points < 4:
        return candles[-target_points:]

    head = candles[0]
    tail = candles[-1]
    body = candles[1:-1]
    bucket_count = max(1, (target_points - 2) // 2)
    bucket_size = max(1, len(body) // bucket_count)

    sampled: list[Candle] = [head]
    for bucket_idx in range(bucket_count):
        start = bucket_idx * bucket_size
        end = len(body) if bucket_idx == bucket_count - 1 else min(len(body), (bucket_idx + 1) * bucket_size)
        chunk = body[start:end]
        if not chunk:
            continue
        low = min(chunk, key=lambda c: float(c.low))
        high = max(chunk, key=lambda c: float(c.high))
        pair = (low, high) if low.ts_open <= high.ts_open else (high, low)
        for item in pair:
            if sampled and sampled[-1].ts_open == item.ts_open:
                continue
            sampled.append(item)

    if sampled[-1].ts_open != tail.ts_open:
        sampled.append(tail)

    if len(sampled) <= target_points:
        return sampled

    pick: list[Candle] = []
    seen_ts: set[int] = set()
    denom = max(1, target_points - 1)
    src_last = len(sampled) - 1
    for i in range(target_points):
        idx = int(round(i * src_last / denom))
        item = sampled[idx]
        if item.ts_open in seen_ts:
            continue
        seen_ts.add(item.ts_open)
        pick.append(item)
    return pick if pick else sampled[-target_points:]


def _draw_price_curve(
    stdscr,
    candles: list[Candle],
    colors: dict[str, int],
    x0: int,
    y0: int,
    width: int,
    height: int,
    marker_rows: list[SignalRow] | None = None,
) -> None:
    if width <= 12 or height <= 5 or not candles:
        return

    clean_candles = [
        c
        for c in candles
        if _is_finite_number(c.open)
        and _is_finite_number(c.high)
        and _is_finite_number(c.low)
        and _is_finite_number(c.close)
        and _is_finite_number(c.volume_est)
        and min(float(c.open), float(c.high), float(c.low), float(c.close)) > 0.0
    ]
    if not clean_candles:
        return

    # Reserve one row at the bottom for x-axis time labels.
    if height <= 6:
        return
    axis_h = 1
    chart_height = height - axis_h
    if chart_height <= 4:
        return

    # Reserve room for price labels so the chart body can stay compact and readable.
    label_w = 9
    if width <= label_w + 8:
        return

    chart_x0 = x0 + label_w
    chart_w = max(4, width - label_w - 1)

    raw_count = len(clean_candles)
    max_points = max(8, chart_w * 2)
    draw_candles = _sample_candles_minmax(clean_candles, target_points=max_points)
    highs = [c.high for c in draw_candles]
    lows = [c.low for c in draw_candles]
    top = max(highs)
    bottom = min(lows)

    span0 = abs(top - bottom)
    pad = max(1e-3, span0 * 0.03, abs(top) * 0.001)
    top += pad
    bottom -= pad
    span = max(1e-9, top - bottom)

    volume_h = 0
    price_h = chart_height
    volume_sep_y: int | None = None
    volume_y0: int | None = None
    if chart_height >= 10:
        volume_h = min(5, max(2, chart_height // 4))
        candidate_price_h = chart_height - volume_h - 1
        if candidate_price_h >= 4:
            price_h = candidate_price_h
            volume_sep_y = y0 + price_h
            volume_y0 = volume_sep_y + 1
        else:
            volume_h = 0

    def _to_y(value: float) -> int:
        ratio = (top - value) / span
        y = y0 + int(round(ratio * max(1, price_h - 1)))
        return max(y0, min(y0 + price_h - 1, y))

    utf = "utf" in (locale.getpreferredencoding(False) or "").lower()
    wick_char = "│" if utf else "|"
    body_char = "█" if utf else "#"

    buy_attr = curses.color_pair(colors.get("BUY", 0)) | curses.A_BOLD
    sell_attr = curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD
    neutral_attr = curses.color_pair(colors.get("SRC", 0))

    tick_rows = sorted({
        y0,
        y0 + (price_h - 1) // 3,
        y0 + (price_h - 1) * 2 // 3,
        y0 + price_h - 1,
    })
    for gy in tick_rows:
        rel = (gy - y0) / max(1, price_h - 1)
        val = top - (span * rel)
        _safe_addstr(stdscr, gy, x0, _truncate(f"{val:>8.2f}", label_w), neutral_attr)

    # Merge multiple source candles that map to the same terminal column.
    # When points are sparse, keep candles contiguous (right-aligned) to avoid a "scatter" look.
    merged: dict[int, list[float | int]] = {}
    if len(draw_candles) <= chart_w:
        start_x = chart_x0 + (chart_w - len(draw_candles))
        for idx, candle in enumerate(draw_candles):
            x = start_x + idx
            merged[x] = [
                idx,
                float(candle.open),
                float(candle.high),
                float(candle.low),
                float(candle.close),
                float(candle.volume_est),
            ]
    else:
        denom = max(1, len(draw_candles) - 1)
        for idx, candle in enumerate(draw_candles):
            x = chart_x0 + int(round(idx * (chart_w - 1) / denom))
            data = merged.get(x)
            if data is None:
                merged[x] = [
                    idx,
                    float(candle.open),
                    float(candle.high),
                    float(candle.low),
                    float(candle.close),
                    float(candle.volume_est),
                ]
                continue
            data[2] = max(float(data[2]), float(candle.high))
            data[3] = min(float(data[3]), float(candle.low))
            data[5] = float(data[5]) + float(candle.volume_est)
            if idx >= int(data[0]):
                data[0] = idx
                data[4] = float(candle.close)

    columns: list[tuple[int, float, float, float, float, float]] = []
    for x in sorted(merged):
        _, o, h, l, c, v = merged[x]
        columns.append((x, float(o), float(h), float(l), float(c), float(v)))

    if not columns:
        return

    # Keep dot/line mode only for ultra-dense windows; most cases stay in candle mode.
    # This avoids "all dots" when n is moderate (e.g. 120 on a normal terminal width).
    line_mode = raw_count > int(chart_w * 3.0)
    line_char = "●" if utf else "*"
    line_seg_char = "─" if utf else "-"
    close_y_by_x: dict[int, int] = {}

    if line_mode:
        close_points: list[tuple[int, int, float, float]] = []
        for x, c_open, _c_high, _c_low, c_close, _c_vol in columns:
            close_points.append((x, _to_y(c_close), c_open, c_close))

        if close_points:
            px, py, _po, pc = close_points[0]
            close_y_by_x[px] = py
            _safe_addstr(stdscr, py, px, line_char, neutral_attr)
            for x, y, c_open, c_close in close_points[1:]:
                attr = buy_attr if c_close >= pc else sell_attr
                dx = max(1, x - px)
                for step in range(dx + 1):
                    cx = px + step
                    cy = int(round(py + (y - py) * (step / dx)))
                    glyph = line_char if step in {0, dx} else line_seg_char
                    _safe_addstr(stdscr, cy, cx, glyph, attr)
                    close_y_by_x[cx] = cy
                px, py, pc = x, y, c_close
    else:
        for x, c_open, c_high, c_low, c_close, _c_vol in columns:
            y_high = _to_y(c_high)
            y_low = _to_y(c_low)
            y_open = _to_y(c_open)
            y_close = _to_y(c_close)
            close_y_by_x[x] = y_close

            attr = buy_attr if c_close >= c_open else sell_attr

            for y in range(min(y_high, y_low), max(y_high, y_low) + 1):
                _safe_addstr(stdscr, y, x, wick_char, neutral_attr)

            y_top = min(y_open, y_close)
            y_bottom = max(y_open, y_close)
            for y in range(y_top, y_bottom + 1):
                _safe_addstr(stdscr, y, x, body_char, attr)

    last_x, last_open, _last_high, _last_low, last_close, _last_vol = columns[-1]
    last_y = _to_y(last_close)
    ref_char = "┈" if utf else "."
    for rx in range(chart_x0, chart_x0 + chart_w):
        _safe_addstr(stdscr, last_y, rx, ref_char, neutral_attr)
    _safe_addstr(stdscr, last_y, last_x, line_char if line_mode else body_char, buy_attr if last_close >= last_open else sell_attr)
    _safe_addstr(
        stdscr,
        last_y,
        x0,
        _truncate(f"{last_close:>8.2f}", label_w),
        buy_attr if last_close >= last_open else sell_attr,
    )

    if volume_h > 0 and volume_y0 is not None and volume_sep_y is not None:
        _safe_hline(stdscr, volume_sep_y, chart_x0, chart_w, neutral_attr)
        _safe_addstr(stdscr, volume_y0, x0, _truncate(f"{'VOL':>8}", label_w), neutral_attr)
        vol_values = [max(float(v), abs(float(c) - float(o))) for _x, o, _h, _l, c, v in columns]
        vol_max = max(vol_values) if vol_values else 0.0
        if vol_max > 0:
            vol_bottom = volume_y0 + volume_h - 1
            vol_char = "▇" if utf else "="
            for (x, c_open, _c_high, _c_low, c_close, _c_vol), v_metric in zip(columns, vol_values):
                ratio = max(0.0, min(1.0, float(v_metric) / float(vol_max)))
                bar_h = max(1, int(round(ratio * volume_h)))
                attr = buy_attr if c_close >= c_open else sell_attr
                for yy in range(vol_bottom - bar_h + 1, vol_bottom + 1):
                    _safe_addstr(stdscr, yy, x, vol_char, attr)

    if marker_rows and close_y_by_x:
        marker_candidates: list[tuple[int, SignalRow]] = []
        first_ts = int(draw_candles[0].ts_open)
        last_ts = int(draw_candles[-1].ts_open)
        span_ts = max(1, last_ts - first_ts)

        for row in marker_rows:
            direction = (row.direction or "").strip().upper()
            if direction not in {"BUY", "SELL", "ALER", "ALERT"}:
                continue
            ts_dt = parse_ts(row.timestamp)
            if ts_dt == datetime.min:
                continue
            ts_s = int(ts_dt.timestamp())
            if ts_s < first_ts or ts_s > last_ts:
                continue
            marker_candidates.append((ts_s, row))

        marker_candidates.sort(key=lambda item: item[0])
        marker_candidates = marker_candidates[-12:]

        marker_seen_x: set[int] = set()
        for ts_s, row in marker_candidates:
            direction = (row.direction or "").strip().upper()
            ratio = (ts_s - first_ts) / span_ts
            x = chart_x0 + int(round(ratio * (chart_w - 1)))
            x = max(chart_x0, min(chart_x0 + chart_w - 1, x))
            if x in marker_seen_x:
                continue
            marker_seen_x.add(x)

            if x in close_y_by_x:
                base_y = close_y_by_x[x]
            else:
                nearest_x = min(close_y_by_x, key=lambda px: abs(px - x))
                base_y = close_y_by_x[nearest_x]

            if direction == "BUY":
                glyph = "▲" if utf else "^"
                attr = buy_attr
                y = max(y0, base_y - 1)
            elif direction == "SELL":
                glyph = "▼" if utf else "v"
                attr = sell_attr
                y = min(y0 + price_h - 1, base_y + 1)
            else:
                glyph = "◆" if utf else "*"
                attr = curses.color_pair(colors.get("ALERT", 0)) | curses.A_BOLD
                y = base_y

            _safe_addstr(stdscr, y, x, glyph, attr)

    axis_y = y0 + chart_height
    axis_attr = curses.color_pair(colors.get("SRC", 0))
    _safe_hline(stdscr, axis_y, chart_x0, chart_w, axis_attr)

    first = draw_candles[0]
    mid = draw_candles[len(draw_candles) // 2]
    last = draw_candles[-1]
    span_ts = max(0, int(last.ts_open) - int(first.ts_open))
    if span_ts >= 2 * 24 * 3600:
        axis_fmt = "%m-%d"
    else:
        axis_fmt = "%H:%M"

    def _fmt_axis_ts(ts_open: int) -> str:
        try:
            return datetime.fromtimestamp(int(ts_open)).strftime(axis_fmt)
        except Exception:
            return "--"

    axis_labels = [
        (chart_x0, _fmt_axis_ts(first.ts_open), "left"),
        (chart_x0 + chart_w // 2, _fmt_axis_ts(mid.ts_open), "center"),
        (chart_x0 + chart_w - 1, _fmt_axis_ts(last.ts_open), "right"),
    ]

    for pos, label, align in axis_labels:
        if not label:
            continue
        if align == "left":
            lx = pos
        elif align == "right":
            lx = pos - len(label) + 1
        else:
            lx = pos - len(label) // 2
        lx = max(chart_x0, min(chart_x0 + chart_w - len(label), lx))
        _safe_addstr(stdscr, axis_y, lx, _truncate(label, max(0, chart_x0 + chart_w - lx)), axis_attr)


def _update_quote_curve(
    curves: dict[str, deque[Candle]],
    symbol: str,
    quote: Quote | None,
    fetched_at: float,
    interval_s: int = 5,
    max_points: int = 240,
) -> None:
    if quote is None:
        return

    sym = (symbol or "").strip().upper()
    if not sym:
        return

    price = float(quote.price)
    if price <= 0 or not _is_finite_number(price):
        return

    ts = float(fetched_at or 0.0)
    if ts <= 0:
        parsed = parse_ts(quote.ts)
        ts = parsed.timestamp() if parsed != datetime.min else time.time()

    step = max(1, int(interval_s))
    bucket = int(ts // step) * step

    buf = curves.get(sym)
    if buf is None:
        buf = deque(maxlen=max(20, int(max_points)))
        curves[sym] = buf

    if not buf or buf[-1].ts_open != bucket:
        buf.append(Candle(ts_open=bucket, open=price, high=price, low=price, close=price, volume_est=0.0, notional_est=0.0))
        return

    prev = buf[-1]
    buf[-1] = Candle(
        ts_open=prev.ts_open,
        open=prev.open,
        high=max(prev.high, price),
        low=min(prev.low, price),
        close=price,
        volume_est=prev.volume_est,
        notional_est=prev.notional_est,
    )


def _snapshot_quote_curves(curves: dict[str, deque[Candle]]) -> dict[str, list[Candle]]:
    return {sym: list(buf) for sym, buf in curves.items()}


def _curve_update_ts(quote: Quote, fetched_at: float, now_ts: float) -> float:
    """Use market timestamp for stale quotes so closed markets do not paint fake live bars."""
    quote_dt = parse_ts(quote.ts)
    if quote_dt == datetime.min:
        return float(fetched_at or now_ts)

    quote_ts = quote_dt.timestamp()
    if (now_ts - quote_ts) >= _CLOSED_CURVE_STALE_SECONDS:
        return quote_ts
    return float(fetched_at or quote_ts)


def _seed_curve_from_intraday_series(
    curves: dict[str, deque[Candle]],
    symbol: str,
    series: list[tuple[int, float, float]],
    *,
    interval_s: int = 60,
    max_points: int = 240,
) -> bool:
    """Replace/seed curve buffer from minute intraday history."""
    sym = (symbol or "").strip().upper()
    if not sym or not series:
        return False

    clean: list[tuple[int, float, float]] = []
    for ts_open, price, volume in series:
        try:
            ts_i = int(ts_open)
            px = float(price)
            vol = float(volume)
        except Exception:
            continue
        if ts_i <= 0 or px <= 0 or not (_is_finite_number(px) and _is_finite_number(vol)):
            continue
        clean.append((ts_i, px, max(0.0, vol)))

    if not clean:
        return False

    clean.sort(key=lambda x: x[0])
    bucket_s = max(1, int(interval_s))
    buffer = deque(maxlen=max(20, int(max_points)))

    prev_close = clean[0][1]
    prev_cum_vol = clean[0][2]
    for ts_open, close_px, cum_vol in clean:
        bucket = int(ts_open // bucket_s) * bucket_s
        open_px = prev_close
        high_px = max(open_px, close_px)
        low_px = min(open_px, close_px)
        vol_delta = max(0.0, cum_vol - prev_cum_vol)
        notional = vol_delta * close_px if vol_delta > 0 else 0.0

        buffer.append(
            Candle(
                ts_open=bucket,
                open=open_px,
                high=high_px,
                low=low_px,
                close=close_px,
                volume_est=vol_delta,
                notional_est=notional,
            )
        )
        prev_close = close_px
        prev_cum_vol = cum_vol

    if not buffer:
        return False

    curves[sym] = buffer
    return True


def _seed_curve_from_daily_series(
    curves: dict[str, deque[Candle]],
    symbol: str,
    series: list[tuple[int, float, float, float, float, float]],
    *,
    max_points: int = 90,
) -> bool:
    """Replace/seed curve buffer from daily OHLCV history."""
    sym = (symbol or "").strip().upper()
    if not sym or not series:
        return False

    clean: list[tuple[int, float, float, float, float, float]] = []
    for ts_open, open_px, high_px, low_px, close_px, volume in series:
        try:
            ts_i = int(ts_open)
            o = float(open_px)
            h = float(high_px)
            l = float(low_px)
            c = float(close_px)
            v = float(volume)
        except Exception:
            continue
        if ts_i <= 0 or o <= 0 or h <= 0 or l <= 0 or c <= 0:
            continue
        if not (_is_finite_number(o) and _is_finite_number(h) and _is_finite_number(l) and _is_finite_number(c) and _is_finite_number(v)):
            continue
        clean.append((ts_i, o, h, l, c, max(0.0, v)))

    if not clean:
        return False

    clean.sort(key=lambda item: item[0])
    buffer = deque(maxlen=max(20, int(max_points)))
    for ts_i, o, h, l, c, v in clean:
        buffer.append(
            Candle(
                ts_open=ts_i,
                open=o,
                high=max(h, o, c),
                low=min(l, o, c),
                close=c,
                volume_est=v,
                notional_est=v * c if v > 0 else 0.0,
            )
        )

    if not buffer:
        return False
    curves[sym] = buffer
    return True


def _maybe_seed_fund_curve_from_daily_history(
    *,
    curves: dict[str, deque[Candle]],
    symbols: set[str],
    bridge: DirectFundBridge,
    attempts: dict[str, float],
    now_ts: float,
    lookback_days: int = 15,
) -> None:
    """
    Seed fund page curves with daily history.

    We fetch at a coarse interval to avoid high-frequency network polling while still keeping
    the chart window in a multi-day context (default 15D).
    """
    days = max(5, int(lookback_days))
    target_span_s = max(24 * 3600, (days - 1) * 24 * 3600)

    for symbol in sorted(symbols):
        existing = curves.get(symbol)
        last_try = float(attempts.get(symbol, 0.0) or 0.0)
        if existing is not None and len(existing) >= max(5, days // 2):
            span_s = max(0.0, float(existing[-1].ts_open - existing[0].ts_open))
            if span_s >= target_span_s and (now_ts - last_try) < _FUND_CN_CURVE_REFRESH_SECONDS:
                continue

        if (now_ts - last_try) < _FUND_CN_CURVE_REFRESH_SECONDS:
            continue
        attempts[symbol] = now_ts

        series = bridge.fetch_daily_candles(symbol, limit=days)
        if not series:
            continue
        seed_curve_from_daily_candles(
            curves,
            symbol,
            series,
            max_points=max(20, days * 3),
        )


def _maybe_seed_closed_curve_from_history(
    *,
    curves: dict[str, deque[Candle]],
    quote_state: QuoteBookState,
    symbols: set[str],
    market: str,
    provider: str,
    attempts: dict[str, float],
    now_ts: float,
    max_points: int = 240,
) -> None:
    """Seed a 1h replay curve for stale (closed-market) symbols."""
    for symbol in sorted(symbols):
        st = quote_state.entries.get(symbol)
        quote = st.quote if st else None
        if quote is None:
            continue

        quote_dt = parse_ts(quote.ts)
        if quote_dt == datetime.min:
            continue

        market_age_s = max(0.0, now_ts - quote_dt.timestamp())
        if market_age_s < _CLOSED_CURVE_STALE_SECONDS:
            attempts.pop(symbol, None)
            continue

        existing = curves.get(symbol)
        if existing is not None and len(existing) >= 2:
            span_s = max(0.0, float(existing[-1].ts_open - existing[0].ts_open))
            if span_s >= _CLOSED_CURVE_TARGET_SPAN_SECONDS:
                continue

        last_try = float(attempts.get(symbol, 0.0) or 0.0)
        if (now_ts - last_try) < _CLOSED_CURVE_RETRY_SECONDS:
            continue
        attempts[symbol] = now_ts

        series = fetch_intraday_curve_1m(
            provider=provider,
            market=market,
            symbol=symbol,
            timeout_s=6.0,
            limit=_CLOSED_CURVE_HISTORY_LIMIT,
        )
        if not series:
            continue

        _seed_curve_from_intraday_series(
            curves,
            symbol,
            series,
            interval_s=60,
            max_points=max_points,
        )


def _draw_market_quad(
    stdscr,
    label: str,
    quote_cfg: QuoteConfig,
    quote_state: QuoteBookState,
    rows: list[SignalRow],
    pane: MasterPaneState,
    colors: dict[str, int],
    curve_map: dict[str, list[Candle]],
    micro_snapshots: dict[str, MicroSnapshot],
    w: int,
    h: int,
    refresh_s: float,
) -> None:
    key_hint = "按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 5基金 | 6港股 | 7资讯 | [/]切换 | +/-加减自选 | r刷新"

    symbols = [s.strip().upper() for s in (quote_cfg.symbols or []) if (s or "").strip()]
    if not (quote_cfg.enabled and symbols):
        _safe_addstr(stdscr, 1, 0, _truncate("行情页：未启用或无标的", w))
        _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))
        return

    pane.selected = min(max(0, pane.selected), max(0, len(symbols) - 1))
    selected_symbol = symbols[pane.selected]
    selected_rows = _signals_for_symbol(rows, selected_symbol, quote_cfg.market)
    selected_state = quote_state.entries.get(selected_symbol)
    selected_quote = selected_state.quote if selected_state else None
    selected_curve = curve_map.get(selected_symbol, [])
    _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))

    panel_top = 1
    panel_h = max(0, h - panel_top - 1)
    if panel_h < 10:
        return

    split_x = max(30, int(w * 0.38))
    if split_x >= w - 28:
        split_x = max(24, w - 28)
    left_w = max(24, split_x)
    right_x = min(w - 1, split_x + 1)
    right_w = max(18, w - right_x)

    right_top_h = int(round(panel_h * 0.62))
    right_top_h = max(8, min(right_top_h, panel_h - 6))
    right_bottom_y = panel_top + right_top_h
    right_bottom_h = panel_h - right_top_h
    if right_bottom_h < 5:
        return

    box_attr = curses.color_pair(colors.get("SRC", 0))
    _draw_box(stdscr, 0, panel_top, left_w, panel_h, box_attr)
    _draw_box(stdscr, right_x, panel_top, right_w, right_top_h, box_attr)
    _draw_box(stdscr, right_x, right_bottom_y, right_w, right_bottom_h, box_attr)

    left_inner_w = max(0, left_w - 2)
    _safe_addstr(stdscr, panel_top, 2, _truncate(f"候选池({len(symbols)})", max(0, left_w - 4)), curses.A_UNDERLINE)

    if left_inner_w >= 56:
        table_cols: list[tuple[str, str, int, str]] = [
            ("idx", "序", 3, "right"),
            ("code", "代码", 10, "left"),
            ("name", "名称", 1, "left"),
            ("last", "最新", 7, "right"),
            ("pct", "涨跌", 7, "right"),
            ("sig", "12h", 4, "right"),
        ]
    elif left_inner_w >= 44:
        table_cols = [
            ("idx", "序", 3, "right"),
            ("code", "代码", 10, "left"),
            ("name", "名称", 1, "left"),
            ("last", "最新", 7, "right"),
            ("pct", "涨跌", 7, "right"),
        ]
    elif left_inner_w >= 34:
        table_cols = [
            ("idx", "序", 3, "right"),
            ("code", "代码", 8, "left"),
            ("name", "名称", 1, "left"),
            ("pct", "涨跌", 7, "right"),
        ]
    else:
        table_cols = [
            ("idx", "序", 3, "right"),
            ("name", "名称", 1, "left"),
            ("pct", "涨跌", 6, "right"),
        ]

    fixed_w = sum(width for key, _, width, _ in table_cols if key != "name")
    field_count = len(table_cols)
    overhead_w = 2 + max(0, field_count - 1)
    resolved_name_w = max(1, left_inner_w - fixed_w - overhead_w)
    resolved_cols: list[tuple[str, str, int, str]] = []
    for key, header, width, align in table_cols:
        if key == "name":
            resolved_cols.append((key, header, resolved_name_w, align))
        else:
            resolved_cols.append((key, header, width, align))

    def _render_left_row(prefix: str, values: dict[str, str]) -> str:
        cells = [_fit_cell(values.get(key, ""), width, align=align) for key, _, width, align in resolved_cols]
        body = " ".join(cells)
        return _fit_cell(f"{prefix} {body}", left_inner_w)

    header_values = {key: header for key, header, _, _ in resolved_cols}
    _safe_addstr(stdscr, panel_top + 1, 1, _render_left_row(" ", header_values), curses.A_UNDERLINE)

    left_body_top = panel_top + 2
    left_body_h = max(0, panel_h - 3)
    pane.left_scroll = min(max(0, pane.left_scroll), max(0, len(symbols) - 1))
    if pane.selected < pane.left_scroll:
        pane.left_scroll = pane.selected
    if pane.selected >= pane.left_scroll + max(1, left_body_h):
        pane.left_scroll = max(0, pane.selected - max(1, left_body_h) + 1)

    now_dt = datetime.now()
    left_visible = symbols[pane.left_scroll : pane.left_scroll + max(1, left_body_h)]
    for i, sym in enumerate(left_visible):
        y = left_body_top + i
        global_idx = pane.left_scroll + i
        st = quote_state.entries.get(sym) or QuoteEntryState(quote=None, last_error="pending", last_fetch_at=0.0)
        q = st.quote
        name = _display_name(sym, q, quote_cfg.market)
        code = _display_symbol(sym, quote_cfg.market)
        prefix = ">" if global_idx == pane.selected else " "

        last_txt = "--"
        pct_txt = "--"
        if q is not None:
            chg = q.price - q.prev_close
            pct = (chg / q.prev_close * 100.0) if q.prev_close else 0.0
            last_txt = f"{q.price:.2f}"
            pct_txt = f"{pct:+.2f}%"

        symbol_rows = _signals_for_symbol(rows, sym, quote_cfg.market)
        row_values = {
            "idx": str(global_idx + 1),
            "code": code,
            "name": name,
            "last": last_txt,
            "pct": pct_txt,
            "sig": str(_count_recent_signal_rows(symbol_rows, now_dt, max_age_s=12 * 60 * 60)),
        }
        _safe_addstr(stdscr, y, 1, _render_left_row(prefix, row_values))

    selected_label = _display_name(selected_symbol, selected_quote, quote_cfg.market)
    selected_disp_symbol = _display_symbol(selected_symbol, quote_cfg.market)
    _safe_addstr(
        stdscr,
        panel_top,
        right_x + 2,
        _truncate(f"标的详情: {selected_label} ({selected_disp_symbol})", max(0, right_w - 4)),
        curses.A_UNDERLINE,
    )

    if selected_quote is None:
        stats_line = "价格=--  涨跌=--  幅度=--  成交量=--  延迟=--  模式=--"
    else:
        selected_chg = selected_quote.price - selected_quote.prev_close
        selected_pct = (selected_chg / selected_quote.prev_close * 100.0) if selected_quote.prev_close else 0.0
        selected_age_s = int(max(0.0, time.time() - (selected_state.last_fetch_at or 0.0))) if selected_state else 0

        curve_mode = "LIVE"
        quote_ts_dt = parse_ts(selected_quote.ts)
        if quote_ts_dt != datetime.min:
            quote_age_s = max(0, int(time.time() - quote_ts_dt.timestamp()))
            if quote_age_s >= _CLOSED_CURVE_STALE_SECONDS:
                curve_span_s = 0.0
                if len(selected_curve) >= 2:
                    curve_span_s = max(0.0, float(selected_curve[-1].ts_open - selected_curve[0].ts_open))
                curve_mode = "CLOSE-1H" if curve_span_s >= _CLOSED_CURVE_TARGET_SPAN_SECONDS else "CLOSE"

        stats_line = (
            f"价格={selected_quote.price:.2f}  涨跌={selected_chg:+.2f} ({selected_pct:+.2f}%)  "
            f"成交量={_fmt_vol(selected_quote.volume)}  延迟={selected_age_s}s  模式={curve_mode}"
        )
    _safe_addstr(stdscr, panel_top + 1, right_x + 1, _truncate(stats_line, max(0, right_w - 2)))

    chart_y = panel_top + 2
    chart_h = max(1, right_top_h - 3)
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

    signal_panel_title = _build_recent_signal_panel_title(selected_rows, now_dt)
    _safe_addstr(stdscr, right_bottom_y, right_x + 2, _truncate(signal_panel_title, max(0, right_w - 4)), curses.A_UNDERLINE)

    right_inner_x = right_x + 1
    right_inner_y = right_bottom_y + 1
    right_inner_w = max(0, right_w - 2)
    right_inner_h = max(0, right_bottom_h - 2)

    # Keep content readable on very narrow terminals.
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
    else:
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

    # Keep footer row for key hints.


def _draw_market_fund_two_panel(
    stdscr,
    quote_cfg: QuoteConfig,
    quote_state: QuoteBookState,
    rows: list[SignalRow],
    pane: MasterPaneState,
    colors: dict[str, int],
    curve_map: dict[str, list[Candle]],
    daily_curve_map: dict[str, list[Candle]],
    micro_snapshots: dict[str, MicroSnapshot],
    w: int,
    h: int,
    refresh_s: float,
    runtime_state: RuntimeState,
) -> None:
    key_hint = "按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 5基金 | 6港股 | 7资讯 | [/]切换标的 | ,.切换领域 | +/-加减自选 | r刷新"
    fund_domain = runtime_state.fund_domain

    # 获取当前选中领域
    domain_profile = get_etf_domain_profile(fund_domain.selected_key)
    domain_label = domain_profile.label or fund_domain.selected_key

    symbols = [s.strip().upper() for s in (quote_cfg.symbols or []) if (s or "").strip()]
    if not (quote_cfg.enabled and symbols):
        _safe_addstr(stdscr, 1, 0, _truncate("行情页：未启用或无标的", w))
        _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))
        return

    pane.selected = min(max(0, pane.selected), max(0, len(symbols) - 1))
    selected_symbol = symbols[pane.selected]
    selected_state = quote_state.entries.get(selected_symbol)
    selected_quote = selected_state.quote if selected_state else None
    selected_rows = _signals_for_symbol(rows, selected_symbol, quote_cfg.market)
    selected_live_curve = curve_map.get(selected_symbol, [])
    selected_curve = daily_curve_map.get(selected_symbol) or selected_live_curve

    top_n_limit = max(1, int(domain_profile.top_n))
    ranking_profile = replace(domain_profile, top_n=max(top_n_limit, len(symbols)))
    ranking_snapshot = select_etf_candidates(
        profile=ranking_profile,
        symbols=symbols,
        quote_entries=quote_state.entries,
        curve_map=curve_map,
        micro_snapshots=micro_snapshots,
        now_ts=time.time(),
        stale_seconds=120,
    )
    model_items = tuple(ranking_snapshot.items)
    top_items = tuple(model_items[:top_n_limit])
    model_rank_map = {item.symbol: idx + 1 for idx, item in enumerate(model_items)}
    model_item_map = {item.symbol: item for item in model_items}
    domain_top_symbols = tuple(symbols[:top_n_limit])
    candidate_rank_map = {sym: idx + 1 for idx, sym in enumerate(symbols)}
    selected_rank = model_rank_map.get(selected_symbol)
    selected_item = model_item_map.get(selected_symbol)
    risk_map = {"LOW": "低", "MED": "中", "HIGH": "高"}

    line2 = (
        f"策略={ranking_snapshot.strategy_label} {ranking_snapshot.strategy_version} | 领域={domain_label} | 覆盖={ranking_snapshot.valid_candidates}/"
        f"{ranking_snapshot.total_candidates} 过期={ranking_snapshot.skipped_stale} | "
        f"口径: cnd=领域相关序 MRank=模型排名 sRank=模型总分 | 更新时间={ranking_snapshot.as_of}"
    )
    _safe_addstr(stdscr, 1, 0, _truncate(line2, w), curses.color_pair(colors.get("SRC", 0)))
    _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))

    panel_top = 2
    panel_h = max(0, h - panel_top - 1)
    if panel_h < 10:
        return

    # 领域列宽度
    domain_col_w = 10
    domain_x = 0

    split_x = max(30, int(w * 0.38))
    if split_x >= w - 28 - domain_col_w:
        split_x = max(24, w - 28 - domain_col_w)
    left_w = max(24, split_x - domain_col_w)
    right_x = min(w - 1, split_x + domain_col_w + 1)
    right_w = max(18, w - right_x)

    right_top_h = int(round(panel_h * 0.58))
    right_top_h = max(8, min(right_top_h, panel_h - 6))
    right_bottom_y = panel_top + right_top_h
    right_bottom_h = panel_h - right_top_h
    if right_bottom_h < 5:
        return

    box_attr = curses.color_pair(colors.get("SRC", 0))
    # 领域列盒子
    _draw_box(stdscr, domain_x, panel_top, domain_col_w, panel_h, box_attr)
    # 候选池盒子（右移）
    _draw_box(stdscr, domain_col_w, panel_top, left_w, panel_h, box_attr)
    _draw_box(stdscr, right_x, panel_top, right_w, right_top_h, box_attr)
    _draw_box(stdscr, right_x, right_bottom_y, right_w, right_bottom_h, box_attr)

    # 绘制领域列标题
    _safe_addstr(stdscr, panel_top, domain_x + 1, _truncate("领域", domain_col_w - 2), curses.A_UNDERLINE)

    # 绘制领域选项
    for i, dkey in enumerate(fund_domain.keys):
        y = panel_top + 1 + i
        if y >= panel_top + panel_h - 1:
            break
        dlabel = get_domain_label(dkey)
        is_selected = dkey == fund_domain.selected_key
        display = _truncate(dlabel, domain_col_w - 2)
        if is_selected:
            _safe_addstr(stdscr, y, domain_x + 1, display, curses.A_REVERSE | curses.color_pair(colors.get("HIGHLIGHT", 0)))
        else:
            _safe_addstr(stdscr, y, domain_x + 1, display)

    left_inner_w = max(0, left_w - 2)
    _safe_addstr(stdscr, panel_top, domain_col_w + 2, _truncate(f"候选池({len(symbols)})", max(0, left_w - 4)), curses.A_UNDERLINE)

    if left_inner_w >= 55:
        table_cols: list[tuple[str, str, int, str]] = [
            ("cand", "候序", 4, "right"),
            ("code", "代码", 10, "left"),
            ("name", "名称", 1, "left"),  # width is resolved dynamically
            ("last", "最新", 7, "right"),
            ("pct", "涨跌", 7, "right"),
            ("rank", "MRank", 5, "right"),
            ("score", "sRank", 6, "right"),
        ]
    elif left_inner_w >= 38:
        table_cols = [
            ("cand", "候序", 4, "right"),
            ("code", "代码", 10, "left"),
            ("name", "名称", 1, "left"),
            ("rank", "MRank", 5, "right"),
            ("score", "sRank", 6, "right"),
        ]
    elif left_inner_w >= 30:
        table_cols = [
            ("cand", "候", 3, "right"),
            ("code", "代码", 8, "left"),
            ("name", "名称", 1, "left"),
            ("rank", "MRk", 4, "right"),
            ("score", "sRk", 5, "right"),
        ]
    else:
        table_cols = [
            ("cand", "候", 3, "right"),
            ("name", "名称", 1, "left"),
            ("rank", "MRk", 4, "right"),
            ("score", "sRk", 5, "right"),
        ]

    fixed_w = sum(width for key, _, width, _ in table_cols if key != "name")
    field_count = len(table_cols)
    # Row layout = prefix(1) + leading blank(1) + fields + blanks between fields.
    overhead_w = 2 + max(0, field_count - 1)
    resolved_name_w = max(1, left_inner_w - fixed_w - overhead_w)
    resolved_cols: list[tuple[str, str, int, str]] = []
    for key, header, width, align in table_cols:
        if key == "name":
            resolved_cols.append((key, header, resolved_name_w, align))
        else:
            resolved_cols.append((key, header, width, align))

    def _render_left_row(prefix: str, values: dict[str, str]) -> str:
        cells = [_fit_cell(values.get(key, ""), width, align=align) for key, _, width, align in resolved_cols]
        body = " ".join(cells)
        return _fit_cell(f"{prefix} {body}", left_inner_w)

    header_values = {key: header for key, header, _, _ in resolved_cols}
    _safe_addstr(stdscr, panel_top + 1, domain_col_w + 1, _render_left_row(" ", header_values), curses.A_UNDERLINE)

    left_body_top = panel_top + 2
    left_body_h = max(0, panel_h - 3)
    pane.left_scroll = min(max(0, pane.left_scroll), max(0, len(symbols) - 1))
    if pane.selected < pane.left_scroll:
        pane.left_scroll = pane.selected
    if pane.selected >= pane.left_scroll + max(1, left_body_h):
        pane.left_scroll = max(0, pane.selected - max(1, left_body_h) + 1)

    left_visible = symbols[pane.left_scroll : pane.left_scroll + max(1, left_body_h)]
    for i, sym in enumerate(left_visible):
        y = left_body_top + i
        candidate_rank = candidate_rank_map.get(sym)
        st = quote_state.entries.get(sym) or QuoteEntryState(quote=None, last_error="pending", last_fetch_at=0.0)
        q = st.quote
        name = _display_name(sym, q, quote_cfg.market)
        code = _display_symbol(sym, quote_cfg.market)
        prefix = ">" if (pane.left_scroll + i) == pane.selected else " "
        rank = model_rank_map.get(sym)
        item = model_item_map.get(sym)
        rank_txt = f"#{rank}" if rank is not None else "--"
        score_txt = f"{item.total_score:.1f}" if item is not None else "--"
        cand_txt = str(candidate_rank) if candidate_rank is not None else "--"
        last_txt = "--"
        pct_txt = "--"
        if q is not None:
            chg = q.price - q.prev_close
            pct = (chg / q.prev_close * 100.0) if q.prev_close else 0.0
            last_txt = f"{q.price:.2f}"
            pct_txt = f"{pct:+.2f}%"

        row_values = {
            "cand": cand_txt,
            "code": code,
            "name": name,
            "last": last_txt,
            "pct": pct_txt,
            "rank": rank_txt,
            "score": score_txt,
        }
        _safe_addstr(stdscr, y, domain_col_w + 1, _render_left_row(prefix, row_values))

    selected_label = _display_name(selected_symbol, selected_quote, quote_cfg.market)
    selected_disp_symbol = _display_symbol(selected_symbol, quote_cfg.market)
    _safe_addstr(
        stdscr,
        panel_top,
        right_x + 2,
        _truncate(f"票详情: {selected_label} ({selected_disp_symbol})", max(0, right_w - 4)),
        curses.A_UNDERLINE,
    )
    if selected_quote is None:
        stats_line = "价格=--  涨跌=--  幅度=--  成交量=--  延迟=--  模式=--"
    else:
        selected_chg = selected_quote.price - selected_quote.prev_close
        selected_pct = (selected_chg / selected_quote.prev_close * 100.0) if selected_quote.prev_close else 0.0
        selected_age_s = int(max(0.0, time.time() - (selected_state.last_fetch_at or 0.0))) if selected_state else 0

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

        stats_line = (
            f"价格={selected_quote.price:.2f}  涨跌={selected_chg:+.2f} ({selected_pct:+.2f}%)  "
            f"成交量={_fmt_vol(selected_quote.volume)}  延迟={selected_age_s}s  模式={curve_mode}  周期={_FUND_CN_CURVE_DAYS}D"
        )
    _safe_addstr(stdscr, panel_top + 1, right_x + 1, _truncate(stats_line, max(0, right_w - 2)))

    chart_y = panel_top + 2
    chart_h = max(1, right_top_h - 3)
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
        code = _display_symbol(sym, quote_cfg.market)
        name = _display_name(sym, rank_state.quote if rank_state else None, quote_cfg.market)
        details.append(f"{idx}. {code} {name} | 角色={role_name}")
    if not conclusion_role_map:
        details.append("当前领域暂无可用结论清单")
    role = conclusion_role_map.get(selected_symbol)
    if role is not None:
        details.append(f"当前票定位: {role}（{domain_label}结论清单）")
    else:
        details.append(f"当前票定位: 非结论清单（{domain_label}候选池）")

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
        rank_name = _display_name(sym, rank_state.quote if rank_state else None, quote_cfg.market)
        rank_symbol = _display_symbol(sym, quote_cfg.market)
        item = model_item_map.get(sym)
        rank = model_rank_map.get(sym)
        rank_txt = f"#{rank}" if rank is not None else "--"
        score_txt = f"{item.total_score:.1f}" if item is not None else "--"
        details.append(f"{idx}. {rank_symbol:<10} {rank_name:<12} MRank={rank_txt} sRank={score_txt}")

    details.append(f"Top{top_n_limit}(模型评分,全池):")
    for idx, item in enumerate(top_items, start=1):
        rank_symbol = _display_symbol(item.symbol, quote_cfg.market)
        rank_state = quote_state.entries.get(item.symbol)
        rank_name = _display_name(item.symbol, rank_state.quote if rank_state else None, quote_cfg.market)
        risk_txt = risk_map.get(item.risk_level, item.risk_level)
        details.append(f"{idx}. {rank_symbol:<10} {rank_name:<12} sRank={item.total_score:>5.1f} 风险={risk_txt}")

    right_body_h = max(0, right_bottom_h - 2)
    for i, line in enumerate(details[: max(1, right_body_h)]):
        _safe_addstr(stdscr, right_bottom_y + 1 + i, right_x + 1, _truncate(line, max(0, right_w - 2)))

    # Keep footer row for key hints.


def _draw_market_micro(
    stdscr,
    snapshot: MicroSnapshot,
    micro_symbols: list[str],
    rows: list[SignalRow],
    quote_state: QuoteBookState,
    curve_map: dict[str, list[Candle]],
    colors: dict[str, int],
    w: int,
    h: int,
) -> None:
    key_hint = "按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 4回测切换 | 5基金 | 6港股 | 7资讯 | [/]切换标的 | r刷新"
    _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))

    symbols = [s.strip().upper() for s in (micro_symbols or []) if (s or "").strip()]
    focus_symbol = (snapshot.symbol or "").strip().upper()
    if focus_symbol and focus_symbol not in symbols:
        symbols.insert(0, focus_symbol)

    if not symbols:
        _safe_addstr(stdscr, 1, 0, _truncate("加密行情：无可用标的（可用 + 添加）", w))
        return

    selected_symbol = focus_symbol if focus_symbol in symbols else symbols[0]
    selected_idx = symbols.index(selected_symbol)
    selected_rows = _signals_for_symbol(rows, selected_symbol, "crypto_spot")
    selected_state = quote_state.entries.get(selected_symbol)
    selected_quote = selected_state.quote if selected_state else None
    selected_curve = curve_map.get(selected_symbol, [])

    panel_top = 1
    panel_h = max(0, h - panel_top - 1)
    if panel_h < 10:
        return

    left_min_w = _adaptive_left_min_width(
        w,
        base_min=_MARKET_MICRO_LEFT_BASE_MIN_WIDTH,
        floor_min=_MARKET_MICRO_LEFT_FLOOR_MIN_WIDTH,
        min_ratio=_MARKET_MICRO_LEFT_MIN_RATIO,
    )
    split_x = max(left_min_w, int(w * _MARKET_MICRO_LEFT_RATIO))
    if split_x >= w - _MARKET_MICRO_RIGHT_MIN_WIDTH:
        split_x = max(left_min_w, w - _MARKET_MICRO_RIGHT_MIN_WIDTH)
    left_w = max(left_min_w, split_x)
    right_x = min(w - 1, split_x + 1)
    right_w = max(18, w - right_x)

    right_top_h = int(round(panel_h * 0.62))
    right_top_h = max(8, min(right_top_h, panel_h - 6))
    right_bottom_y = panel_top + right_top_h
    right_bottom_h = panel_h - right_top_h
    if right_bottom_h < 5:
        return

    box_attr = curses.color_pair(colors.get("SRC", 0))
    _draw_box(stdscr, 0, panel_top, left_w, panel_h, box_attr)
    _draw_box(stdscr, right_x, panel_top, right_w, right_top_h, box_attr)
    _draw_box(stdscr, right_x, right_bottom_y, right_w, right_bottom_h, box_attr)

    left_inner_w = max(0, left_w - 2)
    _safe_addstr(stdscr, panel_top, 2, _truncate(f"候选池({len(symbols)})", max(0, left_w - 4)), curses.A_UNDERLINE)

    if left_inner_w >= 56:
        table_cols: list[tuple[str, str, int, str]] = [
            ("idx", "序", 3, "right"),
            ("code", "代码", 11, "left"),
            ("name", "名称", 1, "left"),
            ("last", "最新", 7, "right"),
            ("pct", "涨跌", 7, "right"),
            ("sig", "12h", 4, "right"),
        ]
    elif left_inner_w >= 46:
        table_cols = [
            ("idx", "序", 3, "right"),
            ("code", "代码", 11, "left"),
            ("name", "名称", 1, "left"),
            ("last", "最新", 7, "right"),
            ("pct", "涨跌", 7, "right"),
        ]
    elif left_inner_w >= 36:
        table_cols = [
            ("idx", "序", 3, "right"),
            ("code", "代码", 9, "left"),
            ("name", "名称", 1, "left"),
            ("last", "最新", 7, "right"),
            ("pct", "涨跌", 7, "right"),
        ]
    else:
        table_cols = [
            ("idx", "序", 3, "right"),
            ("code", "代码", 9, "left"),
            ("last", "最新", 7, "right"),
        ]
        if left_inner_w >= 30:
            table_cols.append(("pct", "涨跌", 7, "right"))
    
    fixed_w = sum(width for key, _, width, _ in table_cols if key != "name")
    field_count = len(table_cols)
    overhead_w = 2 + max(0, field_count - 1)
    resolved_name_w = max(1, left_inner_w - fixed_w - overhead_w)
    resolved_cols: list[tuple[str, str, int, str]] = []
    for key, header, width, align in table_cols:
        if key == "name":
            resolved_cols.append((key, header, resolved_name_w, align))
        else:
            resolved_cols.append((key, header, width, align))

    def _render_left_row(prefix: str, values: dict[str, str]) -> str:
        cells = [_fit_cell(values.get(key, ""), width, align=align) for key, _, width, align in resolved_cols]
        body = " ".join(cells)
        return _fit_cell(f"{prefix} {body}", left_inner_w)

    header_values = {key: header for key, header, _, _ in resolved_cols}
    _safe_addstr(stdscr, panel_top + 1, 1, _render_left_row(" ", header_values), curses.A_UNDERLINE)

    left_body_top = panel_top + 2
    left_body_h = max(0, panel_h - 3)
    left_scroll = 0
    now_dt = datetime.now()
    if selected_idx >= max(1, left_body_h):
        left_scroll = selected_idx - max(1, left_body_h) + 1
    left_visible = symbols[left_scroll : left_scroll + max(1, left_body_h)]

    for i, sym in enumerate(left_visible):
        y = left_body_top + i
        global_idx = left_scroll + i
        st = quote_state.entries.get(sym) or QuoteEntryState(quote=None, last_error="pending", last_fetch_at=0.0)
        q = st.quote
        name = _display_name(sym, q, "crypto_spot")
        code = _display_symbol(sym, "crypto_spot")
        prefix = ">" if global_idx == selected_idx else " "

        last_txt = "--"
        pct_txt = "--"
        if q is not None:
            chg = q.price - q.prev_close
            pct = (chg / q.prev_close * 100.0) if q.prev_close else 0.0
            last_txt = f"{q.price:.2f}"
            pct_txt = f"{pct:+.2f}%"

        symbol_rows = _signals_for_symbol(rows, sym, "crypto_spot")
        row_values = {
            "idx": str(global_idx + 1),
            "code": code,
            "name": name,
            "last": last_txt,
            "pct": pct_txt,
            "sig": str(_count_recent_signal_rows(symbol_rows, now_dt, max_age_s=12 * 60 * 60)),
        }
        _safe_addstr(stdscr, y, 1, _render_left_row(prefix, row_values))

    selected_label = _display_name(selected_symbol, selected_quote, "crypto_spot")
    selected_disp_symbol = _display_symbol(selected_symbol, "crypto_spot")
    _safe_addstr(
        stdscr,
        panel_top,
        right_x + 2,
        _truncate(f"标的详情: {selected_label} ({selected_disp_symbol})", max(0, right_w - 4)),
        curses.A_UNDERLINE,
    )

    if selected_quote is None:
        stats_line = "价格=--  涨跌=--  幅度=--  成交量=--  延迟=--  源=--  模式=--"
    else:
        selected_chg = selected_quote.price - selected_quote.prev_close
        selected_pct = (selected_chg / selected_quote.prev_close * 100.0) if selected_quote.prev_close else 0.0
        selected_age_s = int(max(0.0, time.time() - (selected_state.last_fetch_at or 0.0))) if selected_state else 0
        src = (selected_quote.source or "--").upper()[:8]
        mode = "LIVE" if selected_age_s <= 15 else ("LIVE-SLOW" if selected_age_s <= 120 else "STALE")
        stats_line = (
            f"价格={selected_quote.price:.2f}  涨跌={selected_chg:+.2f} ({selected_pct:+.2f}%)  "
            f"成交量={_fmt_vol(selected_quote.volume)}  延迟={selected_age_s}s  源={src}  模式={mode}"
        )
        if selected_symbol == focus_symbol:
            bias = (snapshot.signals.bias or "NEUTRAL").upper()
            score = float(snapshot.signals.score)
            stats_line += f"  偏向={bias}  评分={score:+.2f}"
    _safe_addstr(stdscr, panel_top + 1, right_x + 1, _truncate(stats_line, max(0, right_w - 2)))

    chart_y = panel_top + 2
    chart_h = max(1, right_top_h - 3)
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

    signal_panel_title = _build_recent_signal_panel_title(selected_rows, now_dt)
    _safe_addstr(stdscr, right_bottom_y, right_x + 2, _truncate(signal_panel_title, max(0, right_w - 4)), curses.A_UNDERLINE)

    right_inner_x = right_x + 1
    right_inner_y = right_bottom_y + 1
    right_inner_w = max(0, right_w - 2)
    right_inner_h = max(0, right_bottom_h - 2)

    # Fallback to legacy single-column rendering on very narrow terminals.
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
    else:
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


