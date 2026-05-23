"""Portfolio NAV / P&L metrics for paper trading."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from tradecat.core.paper_trading.consolidate import consolidate_crypto_positions
from tradecat.core.paper_trading.models import PaperPosition, PortfolioSnapshot, Side
from tradecat.core.paper_trading.repository import BaseRepository
from tradecat.core.symbols import normalize_symbol


def position_unrealized_pnl(pos: PaperPosition, mark_price: Decimal) -> Decimal:
    """Mark-to-market unrealized P&L for an open position."""
    if pos.qty <= 0 or mark_price <= 0:
        return Decimal("0")
    if pos.side == Side.LONG:
        return (mark_price - pos.entry_price) * pos.qty
    if pos.side == Side.SHORT:
        return (pos.entry_price - mark_price) * pos.qty
    return Decimal("0")


def build_mark_prices(raw: dict[str, Decimal] | None) -> dict[str, Decimal]:
    """Normalize symbol keys for mark price lookup."""
    out: dict[str, Decimal] = {}
    for sym, px in (raw or {}).items():
        if px is None or px <= 0:
            continue
        key = normalize_symbol(sym) or sym.strip().upper()
        if key:
            out[key] = px
    return out


def compute_portfolio_summary(
    repo: BaseRepository,
    account_id: UUID,
    *,
    initial_capital: Decimal,
    cash_balance: Decimal,
    mark_prices: dict[str, Decimal] | None = None,
) -> dict:
    """
    NAV model (cash ledger):
      现金 = 账户 balance（已含已实现盈亏与手续费）
      已实现 = 现金 - 初始本金
      净值 = 现金 + 浮动盈亏
      盈亏 = 净值 - 初始本金
    """
    marks = build_mark_prices(mark_prices)
    open_positions = consolidate_crypto_positions(repo.list_positions(account_id))

    unrealized = Decimal("0")
    exposure = Decimal("0")
    margin_used = Decimal("0")
    display_positions: list[PaperPosition] = []

    for pos in open_positions:
        if pos.qty <= 0:
            continue
        mark = marks.get(pos.symbol) or pos.entry_price
        u = position_unrealized_pnl(pos, mark)
        unrealized += u
        exposure += pos.qty * mark
        margin_used += pos.margin
        if hasattr(pos, "model_copy"):
            display_positions.append(pos.model_copy(update={"unrealized_pnl": u}))
        else:
            pos.unrealized_pnl = u
            display_positions.append(pos)

    cash = cash_balance
    realized = cash - initial_capital
    nav = cash + unrealized
    pnl = nav - initial_capital
    if initial_capital > 0:
        pnl_pct = pnl / initial_capital * Decimal("100")
    elif initial_capital < 0:
        pnl_pct = pnl / abs(initial_capital) * Decimal("100")
    else:
        pnl_pct = Decimal("0")
    cash_avail = cash - margin_used

    return {
        "initial_capital": initial_capital,
        "nav": nav,
        "cash_available": cash_avail,
        "cash_balance": cash,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "exposure": exposure,
        "margin_used": margin_used,
        "positions": display_positions,
    }


def update_drawdown_snapshot(
    repo: BaseRepository,
    account_id: UUID,
    *,
    nav: Decimal,
    cash_balance: Decimal,
) -> Decimal:
    """Update peak equity snapshot; return current drawdown %."""
    import datetime as _dt

    snap = repo.get_latest_snapshot(account_id)
    peak = snap.peak_equity if snap else nav
    if nav > peak:
        peak = nav
    drawdown = Decimal("0")
    if peak > 0 and nav < peak:
        drawdown = ((peak - nav) / peak * Decimal("100")).quantize(Decimal("0.01"))
    repo.save_snapshot(
        PortfolioSnapshot(
            ts=_dt.datetime.utcnow(),
            account_id=account_id,
            cash_balance=cash_balance,
            total_equity=nav,
            peak_equity=peak,
            drawdown_pct=drawdown,
        )
    )
    return drawdown
