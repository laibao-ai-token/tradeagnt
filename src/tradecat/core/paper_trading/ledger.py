"""Replay fills to rebuild cash balance and open positions."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from tradecat.core.paper_trading.models import PaperAccount, PaperFill, PaperPosition, Side
from tradecat.core.paper_trading.repository import BaseRepository
from tradecat.core.symbols import normalize_symbol


@dataclass
class _SimPosition:
    side: Side = Side.NEUTRAL
    qty: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    leverage: Decimal = Decimal("1")
    margin: Decimal = Decimal("0")


def _apply_fill_to_sim(pos: _SimPosition, fill: PaperFill, leverage: Decimal) -> Decimal:
    """Update simulated position; return realized P&L cash flow from this fill."""
    realized_delta = Decimal("0")
    if pos.qty <= 0 or pos.side == Side.NEUTRAL:
        pos.side = fill.side
        pos.qty = fill.qty
        pos.entry_price = fill.price
        pos.leverage = leverage
        pos.margin = fill.price * fill.qty / leverage
        return realized_delta

    if pos.side == fill.side:
        total_qty = pos.qty + fill.qty
        total_cost = pos.entry_price * pos.qty + fill.price * fill.qty
        pos.entry_price = total_cost / total_qty
        pos.qty = total_qty
    else:
        if fill.qty >= pos.qty:
            realized_delta = (fill.price - pos.entry_price) * pos.qty
            if pos.side == Side.SHORT:
                realized_delta *= Decimal("-1")
            remaining = fill.qty - pos.qty
            if remaining > 0:
                pos.side = fill.side
                pos.qty = remaining
                pos.entry_price = fill.price
            else:
                pos.side = Side.NEUTRAL
                pos.qty = Decimal("0")
                pos.entry_price = Decimal("0")
        else:
            realized_delta = (fill.price - pos.entry_price) * fill.qty
            if pos.side == Side.SHORT:
                realized_delta *= Decimal("-1")
            pos.qty -= fill.qty

    if pos.qty > 0:
        pos.margin = pos.qty * pos.entry_price / pos.leverage
    else:
        pos.margin = Decimal("0")
        pos.side = Side.NEUTRAL
    return realized_delta


def list_account_fills(repo: BaseRepository, account_id: UUID) -> list[tuple[PaperFill, Decimal]]:
    """Fills for account ordered by timestamp."""
    orders = repo.list_orders(account_id, limit=10_000)
    order_ids = {o.order_id for o in orders}
    leverage_by_order = {o.order_id: o.leverage for o in orders}
    fills: list[tuple[PaperFill, Decimal]] = []
    for oid in order_ids:
        order = repo.get_order(oid)
        if not order:
            continue
        for f in repo.list_fills(account_id, limit=10_000):
            if f.order_id == oid:
                fills.append((f, leverage_by_order.get(oid, Decimal("1"))))
    # list_fills doesn't filter by order well - use raw sql path
    return fills


def _list_fills_chronological(repo: BaseRepository, account_id: UUID) -> list[tuple[PaperFill, Decimal]]:
    import sqlite3

    if not hasattr(repo, "db_path"):
        return list_account_fills(repo, account_id)
    aid = str(account_id)
    sql = """
        SELECT f.fill_id, f.order_id, f.symbol, f.side, f.qty, f.price, f.fee, f.ts,
               COALESCE(o.leverage, '1') AS leverage
        FROM paper_fills f
        JOIN paper_orders o ON f.order_id = o.order_id
        WHERE o.account_id = ? AND o.status = 'FILLED'
        ORDER BY f.ts ASC, f.fill_id ASC
    """
    out: list[tuple[PaperFill, Decimal]] = []
    with sqlite3.connect(repo.db_path) as conn:  # type: ignore[attr-defined]
        conn.row_factory = sqlite3.Row
        for row in conn.execute(sql, (aid,)):
            fill = PaperFill(
                fill_id=row["fill_id"],
                order_id=row["order_id"],
                symbol=row["symbol"],
                side=Side(row["side"]),
                qty=Decimal(row["qty"]),
                price=Decimal(row["price"]),
                fee=Decimal(row["fee"] or "0"),
            )
            out.append((fill, Decimal(row["leverage"] or "1")))
    return out


def rebuild_account_ledger(repo: BaseRepository, account_id: UUID) -> PaperAccount | None:
    """
    Replay all fills with normalized symbols; rewrite positions and cash balance.
    Realized P&L is reflected in balance only (not double-counted on positions).
    """
    acct = repo.get_account(account_id)
    if not acct:
        return None

    if acct.initial_balance is not None:
        initial = acct.initial_balance
    else:
        # 老库无 initial_balance 列时，按默认 1 万本金回放，勿用当前 balance（可能已穿仓）
        initial = Decimal("10000")
        acct.initial_balance = initial

    sim: dict[str, _SimPosition] = {}
    cash = initial

    for fill, leverage in _list_fills_chronological(repo, account_id):
        sym = normalize_symbol(fill.symbol) or fill.symbol.strip().upper()
        fill = fill.model_copy(update={"symbol": sym}) if hasattr(fill, "model_copy") else fill
        pos = sim.setdefault(sym, _SimPosition())
        cash -= fill.fee
        cash += _apply_fill_to_sim(pos, fill, leverage)

    # Clear old position rows for this account
    if hasattr(repo, "_conn"):
        with repo._conn() as conn:  # type: ignore[attr-defined]
            conn.execute("DELETE FROM paper_positions WHERE account_id = ?", (str(account_id),))
            conn.commit()

    for sym, sp in sim.items():
        if sp.qty <= 0:
            continue
        repo.upsert_position(
            PaperPosition(
                account_id=account_id,
                symbol=sym,
                side=sp.side,
                qty=sp.qty,
                entry_price=sp.entry_price,
                margin=sp.margin,
                leverage=sp.leverage,
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
            )
        )

    acct.balance = cash
    if hasattr(repo, "update_account"):
        repo.update_account(acct)  # type: ignore[attr-defined]
    else:
        _update_account_balance(repo, account_id, cash, initial)

    return acct


def _update_account_balance(
    repo: BaseRepository, account_id: UUID, balance: Decimal, initial_balance: Decimal
) -> None:
    import sqlite3

    if not hasattr(repo, "db_path"):
        return
    with sqlite3.connect(repo.db_path) as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE paper_accounts SET balance = ?, initial_balance = ? WHERE account_id = ?",
            (str(balance), str(initial_balance), str(account_id)),
        )
        conn.commit()
