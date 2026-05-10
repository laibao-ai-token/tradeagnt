from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KLine(BaseModel):
    """标准 K 线模型."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class Tick(BaseModel):
    """逐笔成交模型."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    price: float
    volume: float
    timestamp: datetime
    side: str


class OrderBook(BaseModel):
    """订单簿快照模型."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    timestamp: datetime
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
