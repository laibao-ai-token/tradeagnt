"""Risk model definitions for guard validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


RISK_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


@dataclass
class GuardConfig:
    """Configuration for trade guard rules."""

    max_position_pct: float = 0.30
    max_single_symbol_pct: float = 0.20
    cooldown_seconds: int = 300
    max_drawdown_pct: float = 0.15
    max_signal_age_seconds: int = 600
    whitelist: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)
    stop_on_high_risk: bool = True


@dataclass
class GuardResult:
    """Structured result for guard evaluation."""

    passed: bool
    risk_level: str
    reasons: list[str]
    failed_rules: list[str]
    checked_rules: list[str] = field(default_factory=list)
    checked_at: datetime | None = None

