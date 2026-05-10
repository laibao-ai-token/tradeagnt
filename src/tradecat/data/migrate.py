"""Lightweight SQL migration runner (TimescaleDB / PostgreSQL)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import asyncpg


class MigrationRunner:
    """Run numbered ``*.sql`` files inside a directory, tracking state in
    ``schema.migrations``.  Each file is executed as a single block via
    ``asyncpg.Connection.execute``.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def run(self, migrations_dir: Path | str) -> list[str]:
        """Apply pending migrations and return their names."""
        migrations_dir = Path(migrations_dir)
        await self._ensure_tracking()

        applied = await self._get_applied()
        files = sorted(migrations_dir.glob("*.sql"))

        newly_applied: list[str] = []
        for f in files:
            name = f.stem
            if name in applied:
                continue

            sql = f.read_text(encoding="utf-8")
            md5 = hashlib.md5(sql.encode("utf-8")).hexdigest()

            async with self.pool.acquire() as conn:
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema.migrations (name, md5) VALUES ($1, $2)",
                    name,
                    md5,
                )

            newly_applied.append(name)

        return newly_applied

    async def _ensure_tracking(self) -> None:
        sql = """
            CREATE SCHEMA IF NOT EXISTS schema;
            CREATE TABLE IF NOT EXISTS schema.migrations (
                name        TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ DEFAULT NOW(),
                md5         TEXT
            );
        """
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    async def _get_applied(self) -> set[str]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT name FROM schema.migrations")
                return {r["name"] for r in rows}
        except Exception:
            return set()
