"""PaperTradingEngine — orchestrates orders, positions, risk, and execution."""
from __future__ import annotations

import datetime as _dt
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from tradecat.core.symbols import normalize_market, normalize_symbol
from tradecat.core.paper_trading.models import (
    OrderStatus,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PortfolioSnapshot,
    Side,
)
from tradecat.core.paper_trading.consolidate import consolidate_positions_in_repo
from tradecat.core.paper_trading.metrics import compute_portfolio_summary, update_drawdown_snapshot
from tradecat.core.paper_trading.repository import BaseRepository, InMemoryRepository


def _paper_symbol(symbol: str, market: str | None = None) -> str:
    norm = normalize_symbol(symbol, market)
    return norm or (symbol or "").strip().upper()


class RiskGuard:
    """Simple risk checks before order confirmation."""

    def __init__(self, repo: BaseRepository) -> None:
        self._repo = repo

    def check(self, account: PaperAccount, order: PaperOrder) -> tuple[bool, str]:
        """Return (pass, reason)."""
        # Drawdown check
        snap = self._repo.get_latest_snapshot(account.account_id)
        if snap and snap.drawdown_pct > account.max_drawdown_pct:
            return False, f"drawdown {snap.drawdown_pct}% > limit {account.max_drawdown_pct}%"
        # Position limit check
        positions = self._repo.list_positions(account.account_id)
        existing = [p for p in positions if p.symbol == order.symbol]
        if not existing and len(positions) >= account.max_positions:
            return False, f"max positions {account.max_positions} reached"
        # Single trade size check
        max_notional = account.balance * account.max_single_trade_pct
        if order.notional > max_notional:
            return False, f"notional {order.notional} > max {max_notional}"
        return True, ""


class OrderManager:
    """Manages order lifecycle."""

    def __init__(self, repo: BaseRepository) -> None:
        self._repo = repo

    def create(
        self,
        account_id: UUID,
        symbol: str,
        side: Side,
        qty: Decimal,
        entry_price: Decimal,
        leverage: Decimal = Decimal("1.0"),
        idempotency_key: str | None = None,
    ) -> PaperOrder:
        order = PaperOrder(
            account_id=account_id,
            symbol=symbol,
            side=side,
            qty=qty,
            entry_price=entry_price,
            leverage=leverage,
            idempotency_key=idempotency_key,
            status=OrderStatus.PENDING,
        )
        return self._repo.create_order(order)

    def stage(self, order_id: UUID) -> PaperOrder | None:
        o = self._repo.get_order(order_id)
        if o and o.status == OrderStatus.PENDING:
            self._repo.update_order_status(order_id, OrderStatus.STAGED)
            o.status = OrderStatus.STAGED
        return o

    def confirm(self, order_id: UUID) -> PaperOrder | None:
        o = self._repo.get_order(order_id)
        if o and o.status == OrderStatus.STAGED:
            self._repo.update_order_status(order_id, OrderStatus.CONFIRMED)
            o.status = OrderStatus.CONFIRMED
        return o

    def fill(self, order_id: UUID, fill_price: Decimal | None = None) -> PaperFill | None:
        o = self._repo.get_order(order_id)
        if not o or o.status != OrderStatus.CONFIRMED:
            return None
        price = fill_price or o.entry_price
        fee = price * o.qty * o.fee_rate
        self._repo.update_order_status(order_id, OrderStatus.FILLED)
        fill = PaperFill(
            order_id=order_id,
            symbol=o.symbol,
            side=o.side,
            qty=o.qty,
            price=price,
            fee=fee,
            ts=_dt.datetime.now(_dt.timezone.utc),
        )
        self._repo.record_fill(fill)
        return fill

    def rollback(self, order_id: UUID) -> PaperOrder | None:
        o = self._repo.get_order(order_id)
        if o and o.status in (OrderStatus.STAGED, OrderStatus.CONFIRMED):
            self._repo.update_order_status(order_id, OrderStatus.PENDING)
            o.status = OrderStatus.PENDING
        return o


class PositionManager:
    """Aggregates fills into positions per symbol."""

    def __init__(self, repo: BaseRepository) -> None:
        self._repo = repo

    def apply_fill(self, account_id: UUID, fill: PaperFill) -> tuple[PaperPosition, Decimal]:
        symbol = _paper_symbol(fill.symbol)
        fill = fill.model_copy(update={"symbol": symbol}) if hasattr(fill, "model_copy") else fill
        pos = self._repo.get_position(account_id, symbol)
        order = self._repo.get_order(fill.order_id)
        leverage = order.leverage if order else Decimal("1.0")
        realized_delta = Decimal("0")

        if not pos:
            pos = PaperPosition(
                account_id=account_id,
                symbol=symbol,
                side=fill.side,
                qty=fill.qty,
                entry_price=fill.price,
                margin=fill.price * fill.qty / leverage,
                leverage=leverage,
            )
        else:
            if pos.side == fill.side:
                # Same direction — increase position
                total_qty = pos.qty + fill.qty
                total_cost = pos.entry_price * pos.qty + fill.price * fill.qty
                pos.entry_price = total_cost / total_qty
                pos.qty = total_qty
            else:
                # Opposite direction — reduce or flip
                if fill.qty >= pos.qty:
                    realized_delta = (fill.price - pos.entry_price) * pos.qty
                    if pos.side == Side.SHORT:
                        realized_delta *= Decimal("-1")
                    # Flip if remaining
                    remaining = fill.qty - pos.qty
                    if remaining > 0:
                        pos.side = fill.side
                        pos.qty = remaining
                        pos.entry_price = fill.price
                    else:
                        pos.qty = Decimal("0")
                        pos.side = Side.NEUTRAL
                else:
                    # Partial close
                    realized_delta = (fill.price - pos.entry_price) * fill.qty
                    if pos.side == Side.SHORT:
                        realized_delta *= Decimal("-1")
                    pos.qty -= fill.qty
            pos.margin = pos.qty * pos.entry_price / leverage
            if leverage != pos.leverage:
                pos.leverage = leverage
        pos.realized_pnl = Decimal("0")
        self._repo.upsert_position(pos)
        return pos, realized_delta

    def close(self, account_id: UUID, symbol: str, close_price: Decimal) -> tuple[PaperPosition | None, Decimal]:
        symbol = _paper_symbol(symbol)
        pos = self._repo.get_position(account_id, symbol)
        if not pos or pos.qty == 0:
            return None, Decimal("0")
        realized_delta = (close_price - pos.entry_price) * pos.qty
        if pos.side == Side.SHORT:
            realized_delta *= Decimal("-1")
        pos.realized_pnl = Decimal("0")
        pos.unrealized_pnl = Decimal("0")
        pos.qty = Decimal("0")
        pos.side = Side.NEUTRAL
        pos.margin = Decimal("0")
        self._repo.upsert_position(pos)
        return pos, realized_delta


class PaperTradingEngine:
    """Main engine linking signal → order → position → risk."""

    def __init__(self, repo: BaseRepository | None = None) -> None:
        self._repo = repo or InMemoryRepository()
        self.orders = OrderManager(self._repo)
        self.positions = PositionManager(self._repo)
        self.risk = RiskGuard(self._repo)

    # ─── Account ───

    def create_account(self, name: str, balance: Decimal = Decimal("10000"), leverage: Decimal = Decimal("1")) -> PaperAccount:
        acct = PaperAccount(name=name, balance=balance, initial_balance=balance, leverage=leverage)
        return self._repo.create_account(acct)

    def rebuild_ledger(self, account_id: UUID) -> PaperAccount | None:
        from tradecat.core.paper_trading.ledger import rebuild_account_ledger

        return rebuild_account_ledger(self._repo, account_id)

    def get_account(self, account_id: UUID) -> PaperAccount | None:
        return self._repo.get_account(account_id)

    def list_accounts(self) -> list[PaperAccount]:
        return self._repo.list_accounts()

    # ─── Order entry ───

    def _open_order(self, account_id: UUID, symbol: str, side: Side, notional: Decimal, price: Decimal, leverage: Decimal) -> dict:
        """Create, validate, and stage an order."""
        acct = self._repo.get_account(account_id)
        if not acct:
            return {"ok": False, "error": "account not found"}
        symbol = _paper_symbol(symbol)
        if price <= 0:
            return {"ok": False, "error": "invalid price"}
        initial = acct.initial_balance if acct.initial_balance and acct.initial_balance > 0 else Decimal("10000")
        cap_base = acct.balance if acct.balance > 0 else initial
        max_notional = cap_base * acct.max_single_trade_pct
        trade_notional = min(notional, max_notional)
        qty = (trade_notional / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        if qty <= 0:
            return {"ok": False, "error": "qty too small"}
        order = self.orders.create(account_id, symbol, side, qty, price, leverage)
        # Risk guard
        passed, reason = self.risk.check(acct, order)
        if not passed:
            self._repo.update_order_status(order.order_id, OrderStatus.REJECTED)
            order.status = OrderStatus.REJECTED
            return {"ok": False, "error": reason, "order": order}
        # Stage → confirm → fill (simplified: one-shot fill)
        self.orders.stage(order.order_id)
        self.orders.confirm(order.order_id)
        fill = self.orders.fill(order.order_id, price)
        if fill:
            _pos, realized_delta = self.positions.apply_fill(account_id, fill)
            self._apply_cash_delta(account_id, realized_delta, fill.fee)
            return {"ok": True, "order": order, "fill": fill}
        return {"ok": False, "error": "fill failed", "order": order}

    def long(self, account_id: UUID, symbol: str, notional: Decimal, price: Decimal, leverage: Decimal = Decimal("1")) -> dict:
        return self._open_order(account_id, symbol, Side.LONG, notional, price, leverage)

    def short(self, account_id: UUID, symbol: str, notional: Decimal, price: Decimal, leverage: Decimal = Decimal("1")) -> dict:
        return self._open_order(account_id, symbol, Side.SHORT, notional, price, leverage)

    def close(self, account_id: UUID, symbol: str, price: Decimal) -> dict:
        symbol = _paper_symbol(symbol)
        pos, realized_delta = self.positions.close(account_id, symbol, price)
        if not pos:
            return {"ok": False, "error": "no position to close"}
        self._apply_cash_delta(account_id, realized_delta, Decimal("0"))
        return {"ok": True, "position": pos}

    def flip(self, account_id: UUID, symbol: str, notional: Decimal, price: Decimal, leverage: Decimal = Decimal("1")) -> dict:
        """Close existing position and open opposite side."""
        close_result = self.close(account_id, symbol, price)
        if not close_result["ok"]:
            return close_result
        new_side = Side.SHORT if close_result["position"].side == Side.LONG else Side.LONG
        return self._open_order(account_id, symbol, new_side, notional, price, leverage)

    # ─── Queries ───

    def _apply_cash_delta(self, account_id: UUID, realized_delta: Decimal, fee: Decimal) -> None:
        acct = self._repo.get_account(account_id)
        if not acct:
            return
        if acct.initial_balance is None:
            acct.initial_balance = acct.balance
        acct.balance = acct.balance - fee + realized_delta
        if hasattr(self._repo, "update_account"):
            self._repo.update_account(acct)

    def consolidate_positions(self, account_id: UUID) -> int:
        """Merge duplicate symbol rows (e.g. BTCUSDT + BTC_USDT) into one."""
        return consolidate_positions_in_repo(self._repo, account_id)

    def portfolio_summary(
        self,
        account_id: UUID,
        mark_prices: dict[str, Decimal] | None = None,
    ) -> dict:
        """NAV / P&L relative to account balance (initial capital)."""
        acct = self._repo.get_account(account_id)
        # 本金固定为 initial_balance，绝不能回退到当前 balance（穿仓后会把本金显示成负现金）
        if acct and acct.initial_balance is not None:
            initial = acct.initial_balance
        else:
            initial = Decimal("10000")
        cash = acct.balance if acct else Decimal("0")
        summary = compute_portfolio_summary(
            self._repo,
            account_id,
            initial_capital=initial,
            cash_balance=cash,
            mark_prices=mark_prices,
        )
        drawdown = update_drawdown_snapshot(
            self._repo,
            account_id,
            nav=summary["nav"],
            cash_balance=summary["cash_balance"],
        )
        summary["drawdown_pct"] = drawdown
        summary["account"] = acct
        summary["total_equity"] = summary["nav"]
        return summary

    def status(self, account_id: UUID, mark_prices: dict[str, Decimal] | None = None) -> dict:
        summary = self.portfolio_summary(account_id, mark_prices=mark_prices)
        orders = self._repo.list_orders(account_id, limit=20)
        snap = self._repo.get_latest_snapshot(account_id)
        return {
            "account": summary.get("account"),
            "positions": summary["positions"],
            "recent_orders": orders,
            "total_equity": summary["nav"],
            "initial_capital": summary["initial_capital"],
            "nav": summary["nav"],
            "cash_available": summary["cash_available"],
            "realized_pnl": summary["realized_pnl"],
            "unrealized_pnl": summary["unrealized_pnl"],
            "pnl": summary["pnl"],
            "pnl_pct": summary["pnl_pct"],
            "exposure": summary["exposure"],
            "peak_equity": snap.peak_equity if snap else summary["nav"],
            "drawdown_pct": summary["drawdown_pct"],
        }

    def history(self, account_id: UUID, limit: int = 20) -> list:
        return self._repo.list_orders(account_id, limit=limit)

    def recent_fills(self, account_id: UUID, limit: int = 20) -> list:
        """Recent fills newest-first (actual executions, not order intents)."""
        return self._repo.list_fills(account_id, limit=limit)

    def portfolio(self, account_id: UUID) -> dict:
        return self.status(account_id)

    def stats(self, account_id: UUID) -> dict:
        fills = []
        for pos in self._repo.list_positions(account_id):
            fills.extend(self._repo.list_fills(account_id, pos.symbol, limit=100))
        if not fills:
            return {"trades": 0, "win_rate": "N/A", "avg_pnl": "N/A"}

        # Use realized_pnl from positions for accurate P&L
        positions = self._repo.list_positions(account_id)
        closed_positions = [p for p in positions if p.qty == Decimal("0")]
        total_pnl = sum(p.realized_pnl for p in closed_positions)
        win_count = sum(1 for p in closed_positions if p.realized_pnl > 0)

        return {
            "trades": len(fills),
            "win_rate": f"{win_count / len(closed_positions) * 100:.1f}%" if closed_positions else "N/A",
            "avg_pnl": f"{total_pnl / len(closed_positions):.4f}" if closed_positions else "N/A",
            "total_realized_pnl": f"{total_pnl:.4f}",
        }

    # ─── Signal bridge ───

    def from_signal(self, account_id: UUID, payload: dict, price: Decimal) -> dict:
        """Bridge: SignalEngine → PaperTradingEngine order."""
        market = normalize_market(str(payload.get("market", "")))
        symbol = _paper_symbol(str(payload.get("symbol", "")), market or None)
        if not symbol:
            return {"ok": False, "error": "invalid symbol"}
        side_str = payload.get("side", "").upper()
        side = Side(side_str) if side_str in ("LONG", "SHORT", "NEUTRAL") else Side.NEUTRAL
        if side == Side.NEUTRAL:
            return {"ok": False, "error": "invalid side"}
        notional = Decimal(str(payload.get("qty_notional", "0")))
        if notional <= 0:
            acct = self._repo.get_account(account_id)
            if acct:
                notional = acct.balance * acct.max_single_trade_pct
        # Idempotency check
        idem = payload.get("idempotency_key", "")
        if idem:
            existing = self._repo.get_order_by_idempotency(idem)
            if existing:
                return {"ok": False, "error": "idempotency key already exists", "order": existing}
        leverage_raw = payload.get("leverage", "1") or "1"
        try:
            leverage = Decimal(str(leverage_raw))
        except Exception as exc:
            return {"ok": False, "error": f"invalid leverage '{leverage_raw}': {exc}"}
        return self._open_order(account_id, symbol, side, notional, price, leverage)
