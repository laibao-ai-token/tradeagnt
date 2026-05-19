"""Signal engine models: rules, strategy config, signal events."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConditionType(str, Enum):
    STATE_CHANGE = "state_change"
    THRESHOLD_CROSS_UP = "threshold_cross_up"
    THRESHOLD_CROSS_DOWN = "threshold_cross_down"
    CROSS_UP = "cross_up"
    CROSS_DOWN = "cross_down"
    CONTAINS = "contains"
    RANGE_ENTER = "range_enter"
    RANGE_EXIT = "range_exit"
    CUSTOM = "custom"


class IndicatorRef(BaseModel):
    """Indicator reference within a strategy."""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class RuleConfig(BaseModel):
    """Declarative signal rule."""

    name: str
    category: str
    subcategory: str = ""
    direction: str  # BUY | SELL | ALERT
    strength: int = 50
    priority: str = "medium"
    cooldown: int = 300
    min_volume: float = 0
    condition: dict[str, Any] = Field(default_factory=dict)
    message_template: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class StrategyConfig(BaseModel):
    """YAML strategy configuration."""

    name: str
    market: str = "crypto"
    symbols: list[str] = Field(default_factory=list)
    timeframe: str = "1h"
    indicators: list[IndicatorRef] = Field(default_factory=list)
    rules: list[RuleConfig] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)


class SignalEvent(BaseModel):
    """Emitted when a rule triggers."""

    timestamp: datetime
    symbol: str
    timeframe: str
    direction: str
    strength: int
    rule_id: str
    rule_name: str
    price: float
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
