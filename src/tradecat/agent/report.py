"""paper-report JSON builder."""
from __future__ import annotations

import json
from typing import Any

from tradecat.agent.audit import tail_audit
from tradecat.agent.engine import get_paper_engine
from tradecat.agent.envelope import Envelope


def _to_json_safe(obj: Any) -> Any:
    """Convert Pydantic/Decimal/UUID/datetime to JSON-safe Python objects."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def build_paper_report(*, symbol: str | None = None, include_rejects: int = 5) -> Envelope:
    engine = get_paper_engine()
    accounts = engine.list_accounts()
    if not accounts:
        accounts = [engine.create_account("default")]
    account = accounts[0]
    status = engine.status(account.account_id)
    # json.dumps(default=str) 自动处理 Decimal/UUID/datetime
    status_safe = json.loads(json.dumps(status, default=str))
    data: dict[str, Any] = {
        "account_id": str(account.account_id),
        "account_name": account.name,
        "nav": status_safe.get("nav"),
        "cash_available": status_safe.get("cash_available"),
        "pnl": status_safe.get("pnl"),
        "pnl_pct": status_safe.get("pnl_pct"),
        "positions": status_safe.get("positions"),
        "recent_orders": status_safe.get("recent_orders"),
    }
    rejects = [r for r in tail_audit(limit=include_rejects * 3, symbol=symbol) if r.get("outcome") == "reject"]
    data["recent_rejects"] = rejects[:include_rejects]
    return Envelope(ok=True, data=data)
