"""P2 模拟盘 — 彭博风格组合 + 成交终端布局（中文标识）."""
from __future__ import annotations

import curses
from decimal import Decimal

from tradecat.core.symbols.crypto import normalize_crypto_pair
from tradecat.core.symbols.equity import normalize_us_ticker
from tradecat.tui._helpers import (
    _draw_box,
    _fit_cell,
    _fmt_signed,
    _fmt_time,
    _safe_addstr,
    _truncate,
)


def _symbol_market(symbol: str) -> str:
    if normalize_us_ticker(symbol):
        return "us_stock"
    if normalize_crypto_pair(symbol):
        return "crypto"
    return "other"


def _normalize_paper_market(paper_market: str) -> str:
    m = (paper_market or "crypto").strip().lower()
    if m in {"us", "us_stock", "equity"}:
        return "us_stock"
    return "crypto"


def _filter_by_paper_market(items: list, paper_market: str) -> list:
    want = _normalize_paper_market(paper_market)
    out = []
    for item in items:
        sym = getattr(item, "symbol", "") or ""
        if _symbol_market(sym) == want:
            out.append(item)
    return out


def _marks_from_quote_entries(entries: dict, *, market: str = "crypto") -> dict[str, Decimal]:
    """Build mark prices from TUI quote book entries (crypto or US)."""
    marks: dict[str, Decimal] = {}
    for sym, entry in (entries or {}).items():
        q = getattr(entry, "quote", None)
        if q is None or not getattr(q, "price", None):
            continue
        try:
            px = Decimal(str(q.price))
        except Exception:
            continue
        if px <= 0:
            continue
        if market == "us_stock":
            key = normalize_us_ticker(sym) or sym.strip().upper()
        else:
            key = normalize_crypto_pair(sym) or sym.strip().upper()
        if key:
            marks[key] = px
    return marks


def _marks_for_paper_view(
    paper_market: str,
    crypto_entries: dict,
    us_entries: dict,
) -> dict[str, Decimal]:
    """Merged marks for account NAV; per-tab display still filters positions."""
    merged: dict[str, Decimal] = {}
    merged.update(_marks_from_quote_entries(crypto_entries, market="crypto"))
    merged.update(_marks_from_quote_entries(us_entries, market="us_stock"))
    return merged


def _fmt_fill_ts(ts: object) -> str:
    """Paper fills are stored as UTC (naive iso); show local time like the TUI clock."""
    if ts is None:
        return "--"
    raw = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    text = _fmt_time(raw, assume_utc=True)
    return "--" if text == "--:--:--" else text


def _fmt_num(value: object, *, places: int = 2) -> str:
    try:
        return f"{float(value):,.{places}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_qty(value: object) -> str:
    try:
        v = float(value)
        if abs(v) >= 1:
            return f"{v:,.4f}".rstrip("0").rstrip(".")
        return f"{v:.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _side_code(side: object) -> str:
    s = side.value if hasattr(side, "value") else str(side)
    s = s.upper()
    if s == "LONG":
        return "多"
    if s == "SHORT":
        return "空"
    return "-"


def _side_attr(side: object, colors: dict[str, int]) -> int:
    s = side.value if hasattr(side, "value") else str(side)
    s = s.upper()
    if s == "LONG":
        return curses.color_pair(colors.get("BUY", 0))
    if s == "SHORT":
        return curses.color_pair(colors.get("SELL", 0))
    return curses.A_NORMAL


def _pnl_attr(pnl: float, colors: dict[str, int]) -> int:
    if pnl > 0:
        return curses.color_pair(colors.get("BUY", 0))
    if pnl < 0:
        return curses.color_pair(colors.get("SELL", 0))
    return curses.A_NORMAL


def _order_status_code(status: object) -> str:
    st = status.value if hasattr(status, "value") else str(status)
    return {"FILLED": "成", "REJECTED": "拒", "PENDING": "待", "CANCELLED": "撤"}.get(st, st[:1])


def _draw_panel_title(stdscr, y: int, x: int, w: int, title: str, *, bloomberg_code: str) -> None:
    label = f" {bloomberg_code} {title} " if bloomberg_code else f" {title} "
    _safe_addstr(stdscr, y, x + 1, _truncate(label, max(0, w - 2)), curses.A_REVERSE | curses.A_BOLD)


def _draw_table_header(
    stdscr, y: int, x: int, width: int, cols: list[tuple[str, str, int, str]]
) -> None:
    parts: list[str] = []
    for _key, label, col_w, align in cols:
        parts.append(_fit_cell(label, col_w, align=align))
    line = " ".join(parts)
    _safe_addstr(stdscr, y, x, _truncate(line, width), curses.A_UNDERLINE)


def draw_paper_trading_page(
    stdscr,
    h: int,
    w: int,
    colors: dict[str, int],
    *,
    paper_db_path: str,
    mark_prices: dict[str, Decimal] | None = None,
    paper_market: str = "crypto",
) -> None:
    """Bloomberg-style: PORT strip + Holdings + Order blotter (crypto or US sub-view)."""
    paper_market = _normalize_paper_market(paper_market)
    view_label = "美股" if paper_market == "us_stock" else "加密"
    try:
        from tradecat.core.paper_trading.engine import PaperTradingEngine
        from tradecat.core.paper_trading.repository import SqliteRepository

        repo = SqliteRepository(db_path=paper_db_path)
        engine = PaperTradingEngine(repo)
        accounts = engine.list_accounts()
    except Exception:
        accounts = []

    if not accounts:
        try:
            from decimal import Decimal as D

            default_acct = engine.create_account(name="default", balance=D("10000"), leverage=D("1"))
            accounts = [default_acct]
        except Exception:
            pass

    if not accounts:
        for row in range(2, min(h - 1, 12)):
            _safe_addstr(stdscr, row, 0, " " * max(0, w))
        _safe_addstr(stdscr, 3, 2, "暂无模拟盘账户", curses.A_BOLD)
        _safe_addstr(stdscr, 5, 2, "使用 tradecat paper create <名称> 创建账户")
        return

    acct = accounts[0]
    try:
        engine.rebuild_ledger(acct.account_id)
        status = engine.status(acct.account_id, mark_prices=mark_prices)
    except Exception:
        status = {}

    fills: list = []
    fill_total = 0
    try:
        fill_total = len(engine.recent_fills(acct.account_id, limit=500))
        fills = _filter_by_paper_market(
            engine.recent_fills(acct.account_id, limit=20), paper_market
        )
    except Exception:
        fills = []

    positions_all = status.get("positions", [])
    positions = _filter_by_paper_market(positions_all, paper_market)
    try:
        _initial = status.get("initial_capital")
        if _initial is None and getattr(acct, "initial_balance", None) is not None:
            _initial = acct.initial_balance
        initial_f = float(_initial if _initial is not None else 10000)
        nav_f = float(status.get("nav", status.get("total_equity", initial_f)))
        cash_f = float(status.get("cash_available", initial_f))
        pnl = float(status.get("pnl", nav_f - initial_f))
        pnl_pct = float(status.get("pnl_pct", 0))
        realized_f = float(status.get("realized_pnl", 0))
        unrealized_f = float(status.get("unrealized_pnl", 0))
        exposure = float(status.get("exposure", 0))
        dd_f = float(status.get("drawdown_pct", 0) or 0)
    except (TypeError, ValueError):
        initial_f, nav_f, cash_f = 10000.0, 10000.0, 10000.0
        pnl, pnl_pct, realized_f, unrealized_f, exposure, dd_f = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    fill_show_n = len(fills)

    box_attr = curses.color_pair(colors.get("SRC", 0))
    content_top = 3
    content_h = max(6, h - content_top - 1)

    # ── 组合顶栏：净值 = 现金 + 浮盈；已实现 = 现金 - 本金（每次绘制前 rebuild_ledger）──
    port = (
        f" {view_label}模拟 · 组合 {acct.name} "
        f"| 本金 {_fmt_num(initial_f, places=0)} "
        f"| 净值 {_fmt_num(nav_f)} "
        f"| 盈亏 {_fmt_signed(pnl)} ({_fmt_signed(pnl_pct)}%) "
        f"| 现金盈亏 {_fmt_signed(realized_f)} "
        f"| 浮盈 {_fmt_signed(unrealized_f)} "
        f"| 可用 {_fmt_num(cash_f, places=0)} "
        f"| 敞口 {_fmt_num(exposure, places=0)} "
        f"| 回撤 {dd_f:.2f}% "
        f"| 本页持仓 {len(positions)}/{len(positions_all)} "
        f"| 本页流水 {fill_show_n}笔"
    )
    _safe_addstr(stdscr, 2, 0, _truncate(port, w), curses.A_REVERSE | curses.A_BOLD)

    # 清除正文
    for vy in range(content_top, h - 1):
        _safe_addstr(stdscr, vy, 0, " " * max(0, w))

    # ── 双面板：Holdings | Blotter ──
    gap = 1
    blot_w = max(28, min(int(w * 0.38), w - 36))
    hold_w = max(32, w - blot_w - gap)
    if hold_w + blot_w + gap > w:
        hold_w = max(24, w - blot_w - gap)

    hold_x, hold_y = 0, content_top
    blot_x = hold_x + hold_w + gap
    blot_y = content_top

    _draw_box(stdscr, hold_x, hold_y, hold_w, content_h, box_attr)
    _draw_box(stdscr, blot_x, blot_y, blot_w, content_h, box_attr)

    _draw_panel_title(stdscr, hold_y, hold_x, hold_w, "持仓明细", bloomberg_code="")
    _draw_panel_title(stdscr, blot_y, blot_x, blot_w, "最近成交", bloomberg_code="")

    hold_inner_x = hold_x + 1
    hold_inner_w = max(0, hold_w - 2)
    blot_inner_x = blot_x + 1
    blot_inner_w = max(0, blot_w - 2)
    body_y = content_top + 2
    body_h = max(1, content_h - 3)

    # 持仓表
    if hold_inner_w >= 56:
        hold_cols: list[tuple[str, str, int, str]] = [
            ("side", "向", 4, "left"),
            ("sym", "标的", 12, "left"),
            ("qty", "数量", 10, "right"),
            ("avg", "均价", 10, "right"),
            ("mv", "市值", 10, "right"),
            ("upnl", "浮盈", 8, "right"),
        ]
    elif hold_inner_w >= 44:
        hold_cols = [
            ("side", "向", 4, "left"),
            ("sym", "标的", 10, "left"),
            ("qty", "数量", 9, "right"),
            ("avg", "均价", 9, "right"),
            ("upnl", "浮盈", 8, "right"),
        ]
    else:
        hold_cols = [
            ("side", "向", 4, "left"),
            ("sym", "标的", 9, "left"),
            ("qty", "数量", 8, "right"),
        ]

    _draw_table_header(stdscr, body_y, hold_inner_x, hold_inner_w, hold_cols)
    row = body_y + 1
    if positions:
        for pos in positions[:body_h - 1]:
            if row >= hold_y + content_h - 1:
                break
            try:
                pnl_u = float(getattr(pos, "unrealized_pnl", 0) or 0)
            except (TypeError, ValueError):
                pnl_u = 0.0
            mark_px = (mark_prices or {}).get(pos.symbol) if mark_prices else None
            try:
                if mark_px is not None:
                    mv = float(pos.qty) * float(mark_px)
                else:
                    mv = float(pos.qty) * float(pos.entry_price)
            except (TypeError, ValueError):
                mv = 0.0
            values: dict[str, str] = {
                "side": _side_code(pos.side),
                "sym": pos.symbol,
                "qty": _fmt_qty(pos.qty),
                "avg": _fmt_num(pos.entry_price),
                "mv": _fmt_num(mv, places=0),
                "upnl": _fmt_signed(pnl_u),
            }
            cells = [_fit_cell(values.get(k, ""), cw, align=al) for k, _lbl, cw, al in hold_cols]
            line = " ".join(cells)
            attr = _side_attr(pos.side, colors)
            if pnl_u != 0:
                attr |= _pnl_attr(pnl_u, colors)
            _safe_addstr(stdscr, row, hold_inner_x, _truncate(line, hold_inner_w), attr)
            row += 1
    else:
        _safe_addstr(stdscr, row, hold_inner_x + 1, "— 无持仓 —", curses.A_NORMAL)

    # 成交流水（fills：真实成交，按成交时间倒序；数量是单笔成交量，不等于左侧净持仓）
    if blot_inner_w >= 52:
        blot_cols: list[tuple[str, str, int, str]] = [
            ("time", "本地", 8, "left"),
            ("side", "向", 4, "left"),
            ("sym", "标的", 10, "left"),
            ("qty", "数量", 8, "right"),
            ("px", "价格", 9, "right"),
            ("fee", "费", 6, "right"),
        ]
    elif blot_inner_w >= 40:
        blot_cols = [
            ("time", "本地", 8, "left"),
            ("side", "向", 4, "left"),
            ("sym", "标的", 9, "left"),
            ("qty", "数量", 8, "right"),
            ("px", "价格", 8, "right"),
        ]
    else:
        blot_cols = [
            ("time", "本地", 7, "left"),
            ("side", "向", 4, "left"),
            ("sym", "标的", 8, "left"),
            ("px", "价格", 8, "right"),
        ]

    _draw_table_header(stdscr, body_y, blot_inner_x, blot_inner_w, blot_cols)
    row = body_y + 1
    if fills:
        for fill in fills[: body_h - 1]:
            if row >= blot_y + content_h - 1:
                break
            sym = normalize_crypto_pair(fill.symbol) or str(fill.symbol).strip().upper()
            try:
                fee_f = float(fill.fee or 0)
            except (TypeError, ValueError):
                fee_f = 0.0
            values = {
                "time": _fmt_fill_ts(getattr(fill, "ts", None)),
                "side": _side_code(fill.side),
                "sym": sym,
                "qty": _fmt_qty(fill.qty),
                "px": _fmt_num(fill.price),
                "fee": _fmt_num(fee_f, places=2),
            }
            cells = [_fit_cell(values.get(k, ""), cw, align=al) for k, _lbl, cw, al in blot_cols]
            line = " ".join(cells)
            attr = _side_attr(fill.side, colors)
            _safe_addstr(stdscr, row, blot_inner_x, _truncate(line, blot_inner_w), attr)
            row += 1
    else:
        _safe_addstr(stdscr, row, blot_inner_x + 1, "— 无成交 —", curses.A_NORMAL)

    # 竖分隔（宽屏）
    if w >= 70 and gap == 1:
        sep_x = hold_x + hold_w
        for vy in range(content_top, content_top + content_h):
            if vy < h - 1:
                _safe_addstr(stdscr, vy, sep_x, "│", box_attr)
