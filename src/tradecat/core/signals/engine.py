"""SignalEngine: load strategy, run indicators, evaluate rules, emit signals."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals.cooldown import CooldownManager
from tradecat.core.signals.models import ConditionType, RuleConfig, SignalEvent, StrategyConfig


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            text = value.strip().replace(",", "")
            if text.endswith("%"):
                text = text[:-1].strip()
            return float(text)
        except (TypeError, ValueError):
            return default
    return default


def _make_rule_id(rule: RuleConfig) -> str:
    slug = rule.name.replace(" ", "_").replace("-", "_").lower()
    slug = "".join(c for c in slug if c.isalnum() or c == "_")
    return f"{rule.category}.{rule.subcategory}.{slug}"[:60]


def _format_message(rule: RuleConfig, prev: dict | None, curr: dict) -> str:
    fmt_args: dict[str, Any] = {}
    for arg_name, field_name in rule.fields.items():
        if arg_name.startswith("prev_") and prev:
            val = prev.get(field_name)
        else:
            val = curr.get(field_name)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            fmt_args[arg_name] = "N/A"
        else:
            fmt_args[arg_name] = val
    try:
        return rule.message_template.format(**fmt_args)
    except (KeyError, IndexError, ValueError):
        return rule.message_template


def _check_condition(rule: RuleConfig, prev: dict | None, curr: dict) -> bool:
    if not rule.enabled:
        return False

    ct = rule.condition.get("type", "custom")
    cfg = rule.condition

    if ct == ConditionType.STATE_CHANGE:
        if not prev:
            return False
        fld = cfg.get("field", "")
        from_vals = cfg.get("from_values", [])
        to_vals = cfg.get("to_values", [])
        prev_val = str(prev.get(fld, ""))
        curr_val = str(curr.get(fld, ""))
        return prev_val in from_vals and curr_val in to_vals

    elif ct == ConditionType.THRESHOLD_CROSS_UP:
        if not prev:
            return False
        fld = cfg.get("field", "")
        threshold = _to_float(cfg.get("threshold", 0), 0.0)
        prev_val = _to_float(prev.get(fld, 0), 0.0)
        curr_val = _to_float(curr.get(fld, 0), 0.0)
        return prev_val <= threshold < curr_val

    elif ct == ConditionType.THRESHOLD_CROSS_DOWN:
        if not prev:
            return False
        fld = cfg.get("field", "")
        threshold = _to_float(cfg.get("threshold", 0), 0.0)
        prev_val = _to_float(prev.get(fld, 0), 0.0)
        curr_val = _to_float(curr.get(fld, 0), 0.0)
        return prev_val >= threshold > curr_val

    elif ct == ConditionType.CROSS_UP:
        if not prev:
            return False
        fa = cfg.get("field_a", "")
        fb = cfg.get("field_b", "")
        prev_a = _to_float(prev.get(fa, 0), 0.0)
        prev_b = _to_float(prev.get(fb, 0), 0.0)
        curr_a = _to_float(curr.get(fa, 0), 0.0)
        curr_b = _to_float(curr.get(fb, 0), 0.0)
        return prev_a <= prev_b and curr_a > curr_b

    elif ct == ConditionType.CROSS_DOWN:
        if not prev:
            return False
        fa = cfg.get("field_a", "")
        fb = cfg.get("field_b", "")
        prev_a = _to_float(prev.get(fa, 0), 0.0)
        prev_b = _to_float(prev.get(fb, 0), 0.0)
        curr_a = _to_float(curr.get(fa, 0), 0.0)
        curr_b = _to_float(curr.get(fb, 0), 0.0)
        return prev_a >= prev_b and curr_a < curr_b

    elif ct == ConditionType.CONTAINS:
        fld = cfg.get("field", "")
        patterns = cfg.get("patterns", [])
        val = str(curr.get(fld, ""))
        return any(p in val for p in patterns)

    elif ct == ConditionType.RANGE_ENTER:
        if not prev:
            return False
        fld = cfg.get("field", "")
        min_v = _to_float(cfg.get("min_value", float("-inf")), float("-inf"))
        max_v = _to_float(cfg.get("max_value", float("inf")), float("inf"))
        prev_val = _to_float(prev.get(fld, 0), 0.0)
        curr_val = _to_float(curr.get(fld, 0), 0.0)
        return not (min_v <= prev_val <= max_v) and (min_v <= curr_val <= max_v)

    elif ct == ConditionType.RANGE_EXIT:
        if not prev:
            return False
        fld = cfg.get("field", "")
        min_v = _to_float(cfg.get("min_value", float("-inf")), float("-inf"))
        max_v = _to_float(cfg.get("max_value", float("inf")), float("inf"))
        prev_val = _to_float(prev.get(fld, 0), 0.0)
        curr_val = _to_float(curr.get(fld, 0), 0.0)
        return (min_v <= prev_val <= max_v) and not (min_v <= curr_val <= max_v)

    return False


class SignalEngine:
    def __init__(
        self,
        provider_registry: ProviderRegistry,
        indicator_registry: IndicatorRegistry,
        cooldown_manager: CooldownManager | None = None,
    ) -> None:
        self.provider_registry = provider_registry
        self.indicator_registry = indicator_registry
        self.cooldown = cooldown_manager or CooldownManager()

    async def run(
        self,
        config: StrategyConfig,
        symbol: str,
        provider_name: str = "binance",
    ) -> list[SignalEvent]:
        provider = self.provider_registry.resolve_by_name(provider_name)
        df = await provider.fetch_klines(symbol, config.timeframe)

        for ind_ref in config.indicators:
            meta = self.indicator_registry.get(ind_ref.name)
            df = meta.func(df, **ind_ref.params)

        signals: list[SignalEvent] = []
        min_strength = config.thresholds.get("min_strength", 0)

        if self.cooldown.is_active(symbol):
            return signals

        if len(df) >= 2:
            prev = df.iloc[-2].to_dict()
            curr = df.iloc[-1].to_dict()
            last_idx = df.index[-1]
            if isinstance(last_idx, datetime):
                timestamp = last_idx
            elif hasattr(last_idx, "to_pydatetime"):
                timestamp = last_idx.to_pydatetime()
            else:
                timestamp = datetime.now(timezone.utc)

            max_cooldown = 0
            for rule in config.rules:
                if not rule.enabled:
                    continue
                if rule.min_volume > 0:
                    current_volume = _to_float(curr.get("volume"), 0.0)
                    if current_volume < rule.min_volume:
                        continue

                triggered = _check_condition(rule, prev, curr)
                if not triggered or rule.strength < min_strength:
                    continue

                message = _format_message(rule, prev, curr)
                rule_id = _make_rule_id(rule)

                signals.append(
                    SignalEvent(
                        timestamp=timestamp,
                        symbol=symbol,
                        timeframe=config.timeframe,
                        direction=rule.direction,
                        strength=rule.strength,
                        rule_id=rule_id,
                        rule_name=rule.name,
                        price=_to_float(curr.get("close"), 0.0),
                        message=message,
                        metadata={"condition": rule.condition, "priority": rule.priority},
                    )
                )
                max_cooldown = max(max_cooldown, rule.cooldown)

            if signals and max_cooldown > 0:
                self.cooldown.record(symbol, max_cooldown)

        return signals
