"""Order models for trading execution."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


class Order(BaseModel):
    """Trading order generated from a signal."""

    id: str = ""
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    qty: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    signal_id: str = ""
    signal_name: str = ""
    status: str = "pending"  # pending -> submitted -> filled / rejected / cancelled
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
