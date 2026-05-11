"""Paper trading models (Decimal precision throughout)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    STAGED = "STAGED"
    CONFIRMED = "CONFIRMED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PaperAccount(BaseModel):
    """Virtual account configuration."""

    account_id: UUID = Field(default_factory=uuid4)
    name: str = "default"
    balance: Decimal = Decimal("10000.0")
    leverage: Decimal = Decimal("1.0")
    max_drawdown_pct: Decimal = Decimal("10.0")
    max_positions: int = 5
    max_single_trade_pct: Decimal = Decimal("0.95")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PaperOrder(BaseModel):
    """Virtual order lifecycle."""

    order_id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    idempotency_key: str | None = None
    symbol: str
    side: Side
    qty: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.PENDING
    leverage: Decimal = Decimal("1.0")
    slippage_bps: Decimal = Decimal("2.0")
    fee_rate: Decimal = Decimal("0.0004")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def notional(self) -> Decimal:
        return self.qty * self.entry_price


class PaperPosition(BaseModel):
    """Aggregated position per symbol."""

    account_id: UUID
    symbol: str
    side: Side
    qty: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    margin: Decimal = Decimal("0")
    leverage: Decimal = Decimal("1.0")
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def market_value(self) -> Decimal:
        return self.qty * self.entry_price


class PaperFill(BaseModel):
    """Individual fill record."""

    fill_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    ts: datetime = Field(default_factory=datetime.utcnow)


class PortfolioSnapshot(BaseModel):
    """Periodic portfolio state."""

    ts: datetime = Field(default_factory=datetime.utcnow)
    account_id: UUID
    cash_balance: Decimal
    total_equity: Decimal
    peak_equity: Decimal
    drawdown_pct: Decimal = Decimal("0")
