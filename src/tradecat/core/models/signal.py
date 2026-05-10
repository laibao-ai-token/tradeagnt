from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_serializer


class Signal(BaseModel):
    """交易信号模型."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: datetime
    symbol: str
    signal_type: str
    strength: float
    price: float


class Strategy(BaseModel):
    """策略配置模型."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    market: str
    indicators: list[str]
    rules: list[dict[str, Any]]
    thresholds: dict[str, float]


class AnalysisReport(BaseModel):
    """分析报告模型."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    timeframe: str
    indicators_df: pd.DataFrame
    signals: list[Signal]

    @field_serializer("indicators_df")
    def _serialize_df(self, value: pd.DataFrame) -> dict[str, Any]:
        return value.to_dict(orient="list")
