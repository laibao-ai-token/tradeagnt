"""paper-report JSON builder."""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from uuid import UUID

from tradecat.agent.audit import tail_audit
from tradecat.agent.envelope import Envelope
from tradecat.core.paper_trading.engine import PaperTradingEngine


def _paper_engine() -> PaperTradingEngine:
    repo_type = os.getenv("PAPER_REPO_TYPE", "sqlite")
    if repo_type == "memory":
        from tradecat.core.paper_trading import InMemoryRepository

        return PaperTradingEngine(InMemoryRepository())
    from tradecat.core.paper_trading.paths import default_paper_db_path
    from tradecat.core.paper_trading.repository import SqliteRepository

    return PaperTradingEngine(SqliteRepository(db_path=default_paper_db_path()))


def _decimal_to_float(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "model_dump"):
        return _decimal_to_float(obj.model_dump(mode="json"))
    if isinstance(obj, UUID):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(v) for v in obj]
    if isinstance(obj, tuple):
        return [_decimal_to_float(v) for v in obj]
    return obj


def build_paper_report(*, symbol: str | None = None, include_rejects: int = 5) -> Envelope:
    engine = _paper_engine()
    accounts = engine.list_accounts()
    if not accounts:
        accounts = [engine.create_account("default")]
    account = accounts[0]
    status = engine.status(account.account_id)
    data: dict[str, Any] = {
        "account_id": str(account.account_id),
        "account_name": account.name,
        "nav": _decimal_to_float(status.get("nav")),
        "cash_available": _decimal_to_float(status.get("cash_available")),
        "pnl": _decimal_to_float(status.get("pnl")),
        "pnl_pct": _decimal_to_float(status.get("pnl_pct")),
        "positions": _decimal_to_float(status.get("positions")),
        "recent_orders": _decimal_to_float(status.get("recent_orders")),
    }
    rejects = [r for r in tail_audit(limit=include_rejects * 3, symbol=symbol) if r.get("outcome") == "reject"]
    data["recent_rejects"] = rejects[:include_rejects]
    return Envelope(ok=True, data=data)
