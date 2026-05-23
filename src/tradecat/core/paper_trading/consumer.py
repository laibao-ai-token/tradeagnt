"""Signal consumer: poll signal_history.db and auto-execute paper trades.

.. deprecated::
    TUI 路径请使用 ``tradecat.tui.auto_consumer``；本模块保留给 CLI/脚本直连。
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any
from uuid import UUID

from tradecat.core.paper_trading.engine import PaperTradingEngine
from tradecat.core.paper_trading.repository import SqliteRepository


class SignalConsumer:
    """Poll signal_history.db and feed new signals into PaperTradingEngine."""

    def __init__(
        self,
        signal_db_path: str,
        paper_db_path: str,
        account_id: UUID | None = None,
        position_size_pct: float = 0.1,
    ) -> None:
        self.signal_db = signal_db_path
        self.paper_db = paper_db_path
        self.position_size_pct = Decimal(str(position_size_pct))
        self._last_id: int = 0
        repo = SqliteRepository(db_path=paper_db_path)
        self.engine = PaperTradingEngine(repo=repo)
        self._account_id = account_id

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #
    def ensure_account(self, name: str = "auto") -> UUID:
        """Return the default account; create one if absent."""
        if self._account_id:
            acct = self.engine.get_account(self._account_id)
            if acct:
                return self._account_id
        accts = self.engine.list_accounts()
        if accts:
            self._account_id = accts[0].account_id
            return self._account_id
        acct = self.engine.create_account(name=name)
        self._account_id = acct.account_id
        return self._account_id

    def poll(self) -> list[dict[str, Any]]:
        """Fetch new signals since last poll (incremental)."""
        conn = sqlite3.connect(self.signal_db, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM signals WHERE id > ? ORDER BY id ASC",
                (self._last_id,),
            )
            rows = cursor.fetchall()
            if rows:
                self._last_id = max(int(r["id"]) for r in rows)
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def process(self, signal_row: dict[str, Any]) -> dict[str, Any]:
        """Execute one signal through PaperTradingEngine."""
        direction = str(signal_row.get("direction", "")).upper()
        symbol = str(signal_row.get("symbol", "")).strip()
        raw_price = signal_row.get("price")
        if not symbol or raw_price is None:
            return {"ok": False, "error": "missing symbol or price"}
        try:
            price = Decimal(str(raw_price))
        except Exception:
            return {"ok": False, "error": "invalid price"}
        if price <= 0:
            return {"ok": False, "error": "price <= 0"}

        account_id = self.ensure_account()
        acct = self.engine.get_account(account_id)
        if not acct:
            return {"ok": False, "error": "account not found"}

        notional = acct.balance * self.position_size_pct
        if notional <= 0:
            return {"ok": False, "error": "insufficient balance"}

        if direction == "BUY":
            return self.engine.long(account_id, symbol, notional, price)
        elif direction == "SELL":
            return self.engine.short(account_id, symbol, notional, price)
        elif direction == "CLOSE":
            return self.engine.close(account_id, symbol, price)
        else:
            return {"ok": False, "error": f"unsupported direction: {direction}"}

    def run_once(self) -> list[dict[str, Any]]:
        """Poll once and execute all new signals. Returns result list."""
        signals = self.poll()
        results: list[dict[str, Any]] = []
        for sig in signals:
            results.append(self.process(sig))
        return results
