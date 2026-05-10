"""AsyncPG repository layer for domain persistence."""
from __future__ import annotations

from typing import Any

import asyncpg

from tradecat.data.repositories.cooldown import CooldownRepository
from tradecat.data.repositories.signal import SignalRepository


async def create_repositories(pool: asyncpg.Pool | None = None) -> tuple[Any, Any]:
    """Create repositories from a pool (or None if PG unavailable)."""
    if pool is None:
        return None, None
    return SignalRepository(pool), CooldownRepository(pool)
