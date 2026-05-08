"""Unified guard pipeline for pre-trade risk checks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .models import GuardConfig, GuardResult, RISK_RANK


RULE_RISK_LEVEL = {
    "blacklist": "high",
    "max_position": "high",
    "max_drawdown": "high",
    "whitelist": "medium",
    "max_single_symbol": "medium",
    "cooldown": "medium",
    "data_freshness": "high",
}


class GuardPipeline:
    """Evaluate guard rules and produce a structured risk decision."""

    def __init__(self, config: Optional[GuardConfig] = None):
        self.config = config or GuardConfig()
        self._cooldown_cache: dict[str, datetime] = {}

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _merge_risk_level(current: str, candidate: str) -> str:
        return candidate if RISK_RANK[candidate] > RISK_RANK[current] else current

    def _finalize(
        self,
        *,
        reasons: list[str],
        failed_rules: list[str],
        checked_rules: list[str],
        checked_at: datetime,
        risk_level: str,
    ) -> GuardResult:
        return GuardResult(
            passed=not failed_rules,
            risk_level=risk_level if failed_rules else "low",
            reasons=reasons,
            failed_rules=failed_rules,
            checked_rules=checked_rules,
            checked_at=checked_at,
        )

    def validate_trade_intent(
        self,
        symbol: str,
        side: str,
        size_pct: float,
        current_positions: dict[str, float],
        current_equity: float,
        *,
        peak_equity: float | None = None,
        last_signal_ts: datetime | None = None,
        last_trade_ts: datetime | None = None,
        now: datetime | None = None,
    ) -> GuardResult:
        """Validate trade request against a deterministic guard rule sequence."""
        del side  # Side is reserved for future side-specific checks.

        checked_at = now or self._now()
        reasons: list[str] = []
        failed_rules: list[str] = []
        checked_rules: list[str] = []
        risk_level = "low"

        def _fail(rule: str, reason: str) -> bool:
            nonlocal risk_level
            failed_rules.append(rule)
            reasons.append(reason)
            risk_level = self._merge_risk_level(risk_level, RULE_RISK_LEVEL[rule])
            return self.config.stop_on_high_risk and RULE_RISK_LEVEL[rule] == "high"

        checked_rules.append("blacklist")
        if symbol in self.config.blacklist and _fail("blacklist", f"symbol {symbol} is blacklisted"):
            return self._finalize(
                reasons=reasons,
                failed_rules=failed_rules,
                checked_rules=checked_rules,
                checked_at=checked_at,
                risk_level=risk_level,
            )

        checked_rules.append("whitelist")
        if self.config.whitelist and symbol not in self.config.whitelist:
            _fail("whitelist", f"symbol {symbol} not in whitelist")

        checked_rules.append("max_position")
        total_position = sum(abs(v) for v in current_positions.values())
        if total_position + abs(size_pct) > self.config.max_position_pct and _fail(
            "max_position",
            f"total position {total_position + abs(size_pct):.1%} exceeds max {self.config.max_position_pct:.1%}",
        ):
            return self._finalize(
                reasons=reasons,
                failed_rules=failed_rules,
                checked_rules=checked_rules,
                checked_at=checked_at,
                risk_level=risk_level,
            )

        checked_rules.append("max_single_symbol")
        current_symbol_pct = abs(current_positions.get(symbol, 0.0))
        if current_symbol_pct + abs(size_pct) > self.config.max_single_symbol_pct:
            _fail(
                "max_single_symbol",
                (
                    f"symbol {symbol} position {current_symbol_pct + abs(size_pct):.1%} "
                    f"exceeds max {self.config.max_single_symbol_pct:.1%}"
                ),
            )

        checked_rules.append("cooldown")
        cooldown_ref = last_trade_ts or self._cooldown_cache.get(symbol)
        if cooldown_ref is not None:
            elapsed = (checked_at - cooldown_ref).total_seconds()
            if elapsed < self.config.cooldown_seconds:
                _fail(
                    "cooldown",
                    f"symbol {symbol} in cooldown ({elapsed:.0f}s elapsed, need {self.config.cooldown_seconds}s)",
                )

        checked_rules.append("max_drawdown")
        if peak_equity and peak_equity > 0:
            drawdown = (peak_equity - current_equity) / peak_equity
            if drawdown > self.config.max_drawdown_pct and _fail(
                "max_drawdown",
                f"drawdown {drawdown:.1%} exceeds max {self.config.max_drawdown_pct:.1%}",
            ):
                return self._finalize(
                    reasons=reasons,
                    failed_rules=failed_rules,
                    checked_rules=checked_rules,
                    checked_at=checked_at,
                    risk_level=risk_level,
                )

        checked_rules.append("data_freshness")
        if last_signal_ts is None:
            _fail("data_freshness", "no signal data available")
        else:
            age = (checked_at - last_signal_ts).total_seconds()
            if age > self.config.max_signal_age_seconds:
                _fail(
                    "data_freshness",
                    f"signal data stale: {age:.0f}s old (max {self.config.max_signal_age_seconds}s)",
                )

        return self._finalize(
            reasons=reasons,
            failed_rules=failed_rules,
            checked_rules=checked_rules,
            checked_at=checked_at,
            risk_level=risk_level,
        )

    def validate_data_freshness(
        self,
        last_signal_ts: Optional[datetime],
        max_age_seconds: int | None = None,
        *,
        now: datetime | None = None,
    ) -> GuardResult:
        checked_at = now or self._now()
        max_age = max_age_seconds if max_age_seconds is not None else self.config.max_signal_age_seconds
        if last_signal_ts is None:
            return GuardResult(
                passed=False,
                risk_level="high",
                reasons=["no signal data available"],
                failed_rules=["data_freshness"],
                checked_rules=["data_freshness"],
                checked_at=checked_at,
            )
        age = (checked_at - last_signal_ts).total_seconds()
        if age > max_age:
            return GuardResult(
                passed=False,
                risk_level="high",
                reasons=[f"signal data stale: {age:.0f}s old (max {max_age}s)"],
                failed_rules=["data_freshness"],
                checked_rules=["data_freshness"],
                checked_at=checked_at,
            )
        return GuardResult(
            passed=True,
            risk_level="low",
            reasons=[],
            failed_rules=[],
            checked_rules=["data_freshness"],
            checked_at=checked_at,
        )

    def validate_drawdown(self, current_equity: float, peak_equity: float) -> GuardResult:
        checked_at = self._now()
        if peak_equity <= 0:
            return GuardResult(
                passed=True,
                risk_level="low",
                reasons=[],
                failed_rules=[],
                checked_rules=["max_drawdown"],
                checked_at=checked_at,
            )
        drawdown = (peak_equity - current_equity) / peak_equity
        if drawdown > self.config.max_drawdown_pct:
            return GuardResult(
                passed=False,
                risk_level="high",
                reasons=[f"drawdown {drawdown:.1%} exceeds max {self.config.max_drawdown_pct:.1%}"],
                failed_rules=["max_drawdown"],
                checked_rules=["max_drawdown"],
                checked_at=checked_at,
            )
        return GuardResult(
            passed=True,
            risk_level="low",
            reasons=[],
            failed_rules=[],
            checked_rules=["max_drawdown"],
            checked_at=checked_at,
        )

    def record_trade(self, symbol: str, *, ts: datetime | None = None) -> None:
        self._cooldown_cache[symbol] = ts or self._now()
