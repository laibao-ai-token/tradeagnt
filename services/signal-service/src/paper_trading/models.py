"""Core data models for paper trading workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class OrderStatus(Enum):
    PENDING = "PENDING"
    STAGED = "STAGED"
    CONFIRMED = "CONFIRMED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.STAGED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.STAGED: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.CONFIRMED: {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


class Side(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


@dataclass
class PaperOrder:
    order_id: str
    symbol: str
    side: Side
    qty: float
    idempotency_key: str
    entry_price: Optional[float] = None
    entry_ts: Optional[datetime] = None
    entry_score: Optional[int] = None
    entry_reason: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    slippage_bps: float = 0.0
    fee: float = 0.0
    strategy_label: str = "default"
    rejected_reason: Optional[str] = None


@dataclass
class PaperPosition:
    symbol: str
    side: Side
    qty: float
    entry_price: float
    entry_ts: datetime
    mark_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class PortfolioState:
    initial_equity: float
    cash_balance: float
    position_market_value: float
    unrealized_pnl: float
    realized_pnl: float
    total_equity: float
    peak_equity: float
    drawdown_pct: float
    open_positions: int
    return_pct: float


@dataclass
class PaperFill:
    fill_id: str
    order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    slippage_bps: float
    fee: float
    ts: datetime


@dataclass
class PaperLedger:
    orders: dict[str, PaperOrder] = field(default_factory=dict)
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    fills: list[PaperFill] = field(default_factory=list)
    initial_equity: float = 10000.0
    cash_balance: float = 10000.0
    realized_pnl: float = 0.0

    def add_order(self, order: PaperOrder) -> None:
        existing = self.orders.get(order.order_id)
        if existing is not None and existing.idempotency_key == order.idempotency_key:
            return
        self.orders[order.order_id] = order

    def transition_order(self, order_id: str, next_status: OrderStatus, *, rejected_reason: str | None = None) -> bool:
        order = self.orders.get(order_id)
        if order is None:
            return False
        if next_status not in ALLOWED_TRANSITIONS[order.status]:
            return False
        order.status = next_status
        if next_status == OrderStatus.REJECTED and rejected_reason:
            order.rejected_reason = rejected_reason
        return True

    def fill_order(self, order_id: str, fill_price: float, slippage_bps: float, fee: float) -> bool:
        order = self.orders.get(order_id)
        if order is None:
            return False
        if order.status not in {OrderStatus.CONFIRMED, OrderStatus.PENDING}:
            return False
        if order.status != OrderStatus.PENDING:
            transitioned = self.transition_order(order_id, OrderStatus.FILLED)
            if not transitioned:
                return False
        else:
            order.status = OrderStatus.FILLED

        order.entry_price = fill_price
        order.slippage_bps = slippage_bps
        order.fee = fee
        order.entry_ts = order.entry_ts or datetime.now(timezone.utc)

        fill_id = f"{order_id}_fill_{len(self.fills)}"
        fill = PaperFill(
            fill_id=fill_id,
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=fill_price,
            slippage_bps=slippage_bps,
            fee=fee,
            ts=datetime.now(timezone.utc),
        )
        self.fills.append(fill)

        signed_qty = order.qty if order.side == Side.LONG else -order.qty
        if order.symbol in self.positions:
            pos = self.positions[order.symbol]
            pos.qty += signed_qty
            if abs(pos.qty) < 1e-12:
                del self.positions[order.symbol]
        else:
            self.positions[order.symbol] = PaperPosition(
                symbol=order.symbol,
                side=order.side,
                qty=signed_qty,
                entry_price=fill_price,
                entry_ts=datetime.now(timezone.utc),
            )
        return True

    def get_position(self, symbol: str) -> Optional[PaperPosition]:
        return self.positions.get(symbol)

    def get_all_positions(self) -> list[PaperPosition]:
        return list(self.positions.values())

