"""Signal persistence repository."""
from __future__ import annotations

import json

import asyncpg

from tradecat.core.signals.models import SignalEvent


class SignalRepository:
    """Read/write ``signal.history`` hypertable."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def save(self, event: SignalEvent) -> None:
        """Insert a signal event."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO signal.history
                (symbol, timeframe, direction, strength, rule_id, rule_name,
                 timestamp, price, message, raw_data)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                event.symbol,
                event.timeframe,
                event.direction,
                event.strength,
                event.rule_id,
                event.rule_name,
                event.timestamp,
                event.price,
                event.message,
                json.dumps(event.metadata),
            )

    async def get_recent(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> list[SignalEvent]:
        """Return recent signals for a symbol/timeframe."""
        rows = await self.pool.fetch(
            """
            SELECT symbol, timeframe, direction, strength, rule_id, rule_name,
                   timestamp, price, message, raw_data
            FROM signal.history
            WHERE symbol = $1 AND timeframe = $2
            ORDER BY timestamp DESC
            LIMIT $3
            """,
            symbol,
            timeframe,
            limit,
        )
        return [self._row_to_event(r) for r in rows]

    def _row_to_event(self, row: asyncpg.Record) -> SignalEvent:
        raw = row["raw_data"]
        metadata: dict = json.loads(raw) if raw else {}
        return SignalEvent(
            timestamp=row["timestamp"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            direction=row["direction"],
            strength=row["strength"],
            rule_id=row["rule_id"],
            rule_name=row["rule_name"],
            price=float(row["price"]) if row["price"] is not None else 0.0,
            message=row["message"] or "",
            metadata=metadata,
        )
