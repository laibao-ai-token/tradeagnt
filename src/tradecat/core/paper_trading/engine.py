"""PaperTradingEngine — orchestrates orders, positions, risk, and execution."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from tradecat.core.paper_trading.models import (
    OrderStatus,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PortfolioSnapshot,
    Side,
)
from tradecat.core.paper_trading.repository import BaseRepository, InMemoryRepository


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

    def apply_fill(self, account_id: UUID, fill: PaperFill) -> PaperPosition:
        pos = self._repo.get_position(account_id, fill.symbol)
        if not pos:
            pos = PaperPosition(
                account_id=account_id,
                symbol=fill.symbol,
                side=fill.side,
                qty=fill.qty,
                entry_price=fill.price,
                margin=fill.price * fill.qty / Decimal("1.0"),  # leverage=1 default
                leverage=Decimal("1.0"),
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
                    realized = (fill.price - pos.entry_price) * pos.qty
                    if pos.side == Side.SHORT:
                        realized *= Decimal("-1")
                    pos.realized_pnl += realized
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
                    realized = (fill.price - pos.entry_price) * fill.qty
                    if pos.side == Side.SHORT:
                        realized *= Decimal("-1")
                    pos.realized_pnl += realized
                    pos.qty -= fill.qty
            pos.margin = pos.qty * pos.entry_price / pos.leverage
        self._repo.upsert_position(pos)
        return pos

    def close(self, account_id: UUID, symbol: str, close_price: Decimal) -> PaperPosition | None:
        pos = self._repo.get_position(account_id, symbol)
        if not pos or pos.qty == 0:
            return None
        realized = (close_price - pos.entry_price) * pos.qty
        if pos.side == Side.SHORT:
            realized *= Decimal("-1")
        pos.realized_pnl += realized
        pos.unrealized_pnl = Decimal("0")
        pos.qty = Decimal("0")
        pos.side = Side.NEUTRAL
        pos.margin = Decimal("0")
        self._repo.upsert_position(pos)
        return pos


class PaperTradingEngine:
    """Main engine linking signal → order → position → risk."""

    def __init__(self, repo: BaseRepository | None = None) -> None:
        self._repo = repo or InMemoryRepository()
        self.orders = OrderManager(self._repo)
        self.positions = PositionManager(self._repo)
        self.risk = RiskGuard(self._repo)

    # ─── Account ───

    def create_account(self, name: str, balance: Decimal = Decimal("10000"), leverage: Decimal = Decimal("1")) -> PaperAccount:
        acct = PaperAccount(name=name, balance=balance, leverage=leverage)
        return self._repo.create_account(acct)

    def get_account(self, account_id: UUID) -> PaperAccount | None:
        return self._repo.get_account(account_id)

    # ─── Order entry ───

    def _open_order(self, account_id: UUID, symbol: str, side: Side, notional: Decimal, price: Decimal, leverage: Decimal) -> dict:
        """Create, validate, and stage an order."""
        acct = self._repo.get_account(account_id)
        if not acct:
            return {"ok": False, "error": "account not found"}
        qty = (notional / price).quantize(Decimal("0.000001"))
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
            self.positions.apply_fill(account_id, fill)
            return {"ok": True, "order": order, "fill": fill}
        return {"ok": False, "error": "fill failed", "order": order}

    def long(self, account_id: UUID, symbol: str, notional: Decimal, price: Decimal, leverage: Decimal = Decimal("1")) -> dict:
        return self._open_order(account_id, symbol, Side.LONG, notional, price, leverage)

    def short(self, account_id: UUID, symbol: str, notional: Decimal, price: Decimal, leverage: Decimal = Decimal("1")) -> dict:
        return self._open_order(account_id, symbol, Side.SHORT, notional, price, leverage)

    def close(self, account_id: UUID, symbol: str, price: Decimal) -> dict:
        pos = self.positions.close(account_id, symbol, price)
        if not pos:
            return {"ok": False, "error": "no position to close"}
        return {"ok": True, "position": pos}

    def flip(self, account_id: UUID, symbol: str, notional: Decimal, price: Decimal, leverage: Decimal = Decimal("1")) -> dict:
        """Close existing position and open opposite side."""
        close_result = self.close(account_id, symbol, price)
        if not close_result["ok"]:
            return close_result
        new_side = Side.SHORT if close_result["position"].side == Side.LONG else Side.LONG
        return self._open_order(account_id, symbol, new_side, notional, price, leverage)

    # ─── Queries ───

    def status(self, account_id: UUID) -> dict:
        acct = self._repo.get_account(account_id)
        positions = self._repo.list_positions(account_id)
        orders = self._repo.list_orders(account_id, limit=20)
        # Simple equity calc
        total_equity = acct.balance if acct else Decimal("0")
        for p in positions:
            total_equity += p.realized_pnl
        snap = self._repo.get_latest_snapshot(account_id)
        peak = snap.peak_equity if snap else total_equity
        drawdown = Decimal("0")
        if peak > 0 and total_equity < peak:
            drawdown = ((peak - total_equity) / peak * 100).quantize(Decimal("0.01"))
        return {
            "account": acct,
            "positions": positions,
            "recent_orders": orders,
            "total_equity": total_equity,
            "peak_equity": peak,
            "drawdown_pct": drawdown,
        }

    def history(self, account_id: UUID, limit: int = 20) -> list:
        return self._repo.list_orders(account_id, limit=limit)

    def portfolio(self, account_id: UUID) -> dict:
        return self.status(account_id)

    def stats(self, account_id: UUID) -> dict:
        fills = []
        for pos in self._repo.list_positions(account_id):
            fills.extend(self._repo.list_fills(account_id, pos.symbol, limit=100))
        if not fills:
            return {"trades": 0, "win_rate": "N/A", "avg_pnl": "N/A"}
        # Simplified stats
        pnls = [f.price * f.qty for f in fills]
        wins = [p for p in pnls if p > 0]
        return {
            "trades": len(fills),
            "win_rate": f"{len(wins)/len(fills)*100:.1f}%" if fills else "N/A",
            "avg_pnl": f"{sum(pnls)/len(pnls):.4f}" if pnls else "N/A",
        }

    # ─── Signal bridge ───

    def from_signal(self, account_id: UUID, payload: dict, price: Decimal) -> dict:
        """Bridge: SignalEngine → PaperTradingEngine order."""
        symbol = payload.get("symbol", "")
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
        return self._open_order(account_id, symbol, side, notional, price)
