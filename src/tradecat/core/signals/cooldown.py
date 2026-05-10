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

    async def is_active_async(self, symbol: str) -> bool:
        """Check memory + optional PG for persistent cooldown."""
        if self.is_active(symbol):
            return True
        if self._pg is not None:
            try:
                from tradecat.data.repositories.cooldown import (  # noqa: PLC0415
                    CooldownRepository,
                )

                repo = CooldownRepository(self._pg)
                return await repo.is_active(symbol)
            except Exception:
                pass
        return False

    async def record_async(self, symbol: str, cooldown_seconds: int) -> None:
        self.record(symbol, cooldown_seconds)
        if self._pg is not None:
            try:
                from tradecat.data.repositories.cooldown import (  # noqa: PLC0415
                    CooldownRepository,
                )

                repo = CooldownRepository(self._pg)
                await repo.record(symbol, cooldown_seconds)
            except Exception:
                pass
