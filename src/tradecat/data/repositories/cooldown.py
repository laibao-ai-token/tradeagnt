"""Cooldown persistence repository."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncpg


class CooldownRepository:
    """Read/write ``signal.cooldown``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def is_active(self, symbol: str) -> bool:
        row = await self.pool.fetchrow(
            "SELECT cool_until FROM signal.cooldown WHERE symbol = $1",
            symbol,
        )
        if row and row["cool_until"] > datetime.now(timezone.utc):
            return True
        return False

    async def record(self, symbol: str, cooldown_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        cool_until = now + timedelta(seconds=cooldown_seconds)
        await self.pool.execute(
            """
            INSERT INTO signal.cooldown (symbol, last_fired, cool_until)
            VALUES ($1, $2, $3)
            ON CONFLICT (symbol) DO UPDATE SET
                last_fired = EXCLUDED.last_fired,
                cool_until = EXCLUDED.cool_until
            """,
            symbol,
            now,
            cool_until,
        )
