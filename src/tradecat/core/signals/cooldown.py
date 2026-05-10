"""Cooldown manager (in-memory; PG persistence optional)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


class CooldownManager:
    """Per-symbol cooldown tracker.

    Stores state in-memory for fast synchronous access.
    Optional *pg_pool* enables async PG persistence; the caller
    should await ``record_async`` / ``is_active_async`` when a pool
    is provided.
    """

    def __init__(self, pg_pool: Any | None = None) -> None:
        self._memory: dict[str, datetime] = {}
        self._pg = pg_pool

    def is_active(self, symbol: str) -> bool:
        cool_until = self._memory.get(symbol)
        if cool_until and cool_until > datetime.now(timezone.utc):
            return True
        if cool_until:
            del self._memory[symbol]
        return False

    def record(self, symbol: str, cooldown_seconds: int) -> None:
        self._memory[symbol] = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
