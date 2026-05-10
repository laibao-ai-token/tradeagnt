"""AsyncPG connection pool wrapper."""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool(dsn: str | None = None) -> asyncpg.Pool:
    """Idempotent pool initialiser."""
    global _pool
    if _pool is None:
        dsn = dsn or os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:***@localhost:5434/market_data",
        )
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    """Close the shared pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    """Yield an acquired connection."""
    pool = await init_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_transaction() -> AsyncGenerator[asyncpg.Connection, None]:
    """Yield a transaction-wrapped connection."""
    pool = await init_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
