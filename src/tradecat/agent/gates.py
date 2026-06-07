"""G2–G5 gates for submit-thesis."""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from uuid import UUID

from tradecat.agent.envelope import Envelope, fail
from tradecat.core.paper_trading.engine import PaperTradingEngine
from tradecat.core.paper_trading.models import Side
from tradecat.core.symbols import infer_market_from_symbol, normalize_market, normalize_symbol


def gate_snapshot() -> dict[str, str]:
    return {
        "schema": "pending",
        "risk": "pending",
        "symbol": "pending",
        "conflict": "pending",
        "freshness": "pending",
    }


def check_risk(thesis: dict[str, Any]) -> Envelope | None:
    direction = str(thesis.get("direction") or "").upper()
    if direction == "WATCH_ONLY":
        return None
    intent = thesis.get("paper_intent")
    if not isinstance(intent, dict):
        return fail("agent_sizing_required", "paper_intent required for LONG/SHORT", gate="risk")
    margin = intent.get("requested_margin_usdt")
    leverage = intent.get("paper_leverage")
    if margin is None or float(margin) <= 0:
        return fail("agent_sizing_required", "requested_margin_usdt required", gate="risk")
    if leverage is None or float(leverage) <= 0 or float(leverage) > 100:
        return fail("agent_sizing_required", "paper_leverage must be in (0, 100]", gate="risk")
    for field in ("invalidation_price", "take_profit_price"):
        val = thesis.get(field)
        if val is None or float(val) <= 0:
            return fail("agent_sizing_required", f"{field} required for LONG/SHORT", gate="risk")
    return None


def check_symbol(thesis: dict[str, Any]) -> tuple[Envelope | None, str, str]:
    raw = str(thesis.get("symbol") or "").strip()
    market = infer_market_from_symbol(raw)
    norm = normalize_symbol(raw, market)
    if not norm:
        return fail("agent_symbol_unsupported", f"cannot normalize symbol: {raw}", gate="symbol"), "", ""
    return None, norm, normalize_market(market)


def check_conflict(
    engine: PaperTradingEngine,
    account_id: UUID,
    symbol: str,
    direction: str,
) -> tuple[Envelope | None, str, list[str]]:
    """Return (error, gate_status, warnings). gate_status: pass|warn|fail."""
    warnings: list[str] = []
    strict = (os.getenv("TRADEAGNT_AGENT_CONFLICT") or "").strip().lower() == "strict"
    status = engine.status(account_id)
    positions = status.get("positions") or []
    pos = next((p for p in positions if getattr(p, "symbol", None) == symbol and getattr(p, "qty", 0) > 0), None)
    if not pos:
        return None, "pass", warnings
    target = Side.LONG if direction == "LONG" else Side.SHORT if direction == "SHORT" else None
    if target is None:
        return None, "pass", warnings
    if pos.side == target:
        return (
            fail("agent_position_conflict", "same-direction position already open", gate="conflict"),
            "fail",
            warnings,
        )
    warnings.append("position_conflict")
    if strict:
        return (
            fail("agent_position_conflict", "opposite position conflict (strict)", gate="conflict"),
            "fail",
            warnings,
        )
    return None, "warn", warnings


def fetch_quote_price(symbol: str, market: str) -> tuple[Decimal | None, int | None, list[str]]:
    """Public quote only (no API keys). Returns (price, age_ms, warnings)."""
    warnings: list[str] = []
    try:
        from tradecat.tui.quote import fetch_quote

        m = normalize_market(market)
        provider = "tencent" if m == "us_stock" else "tencent" if m in {"cn_stock", "hk_stock"} else "auto"
        market_arg = m if m in {"us_stock", "cn_stock", "hk_stock", "crypto_spot"} else "crypto_spot"
        if m == "crypto":
            market_arg = "crypto_spot"
        q = fetch_quote(provider, market_arg, symbol, timeout_s=8.0)
        if q is None or q.price <= 0:
            return None, None, ["quote_unavailable"]
        age_ms = None
        if q.ts:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).timestamp()
            try:
                ts_val = float(q.ts)
            except (TypeError, ValueError):
                ts_val = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                    try:
                        ts_val = datetime.strptime(str(q.ts).strip(), fmt).replace(tzinfo=timezone.utc).timestamp()
                        break
                    except ValueError:
                        continue
            if ts_val is not None:
                age_ms = int(max(0, (now - ts_val) * 1000))
        return Decimal(str(q.price)), age_ms, warnings
    except Exception as exc:
        return None, None, [f"quote_error:{exc}"]
