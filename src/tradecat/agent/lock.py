"""Per-thesis claim lock for submit-thesis concurrency safety.

Race fix: same ``thesis_id`` submitted concurrently can both pass
``find_accepted`` (audit not yet written) and double-open positions.

Solution: SQLite atomic ``INSERT OR IGNORE`` on a thesis_id-keyed table.
The first caller wins; concurrent callers see the row and return
``idempotent_replay`` (safe, in-flight or already-accepted).

DB path: ``libs/database/services/signal-service/.agent_thesis_lock.db``
(co-located with paper_trading.db). Override via ``TRADEAGNT_AGENT_LOCK_PATH``.

Schema::

    CREATE TABLE agent_thesis_lock (
        thesis_id TEXT PRIMARY KEY,
        accepted_at INTEGER,        -- ms epoch; NULL while in-flight
        claimed_at INTEGER NOT NULL -- ms epoch
    );

TTL: 1h for stale-claim takeover (covers process crash). Override per call.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from tradecat.core.paper_trading.paths import find_tradeagnt_repo_root

DEFAULT_TTL_MS = 60 * 60 * 1000
DEFAULT_DB_NAME = ".agent_thesis_lock.db"


def _db_path() -> Path:
    env = os.getenv("TRADEAGNT_AGENT_LOCK_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    root = find_tradeagnt_repo_root()
    return root / "libs" / "database" / "services" / "signal-service" / DEFAULT_DB_NAME


def _ensure_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_thesis_lock ("
            "thesis_id TEXT PRIMARY KEY, "
            "accepted_at INTEGER, "
            "claimed_at INTEGER NOT NULL)"
        )
        conn.commit()


def _get_conn() -> sqlite3.Connection:
    path = _db_path()
    _ensure_schema(path)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def claim(thesis_id: str, *, ttl_ms: int = DEFAULT_TTL_MS) -> dict[str, Any]:
    """Atomically claim ``thesis_id`` for processing.

    Returns dict with keys:
      - ``acquired`` (bool): True if we own the lock
      - ``reason`` (str): ``claimed`` | ``took_over_stale`` | ``already_accepted`` | ``in_flight``
      - ``prior`` (dict|None): existing state if not acquired
    """
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - ttl_ms
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO agent_thesis_lock(thesis_id, accepted_at, claimed_at) "
            "VALUES (?, NULL, ?)",
            (thesis_id, now_ms),
        )
        if cur.rowcount == 1:
            return {"acquired": True, "reason": "claimed", "prior": None}
        cur = conn.execute(
            "UPDATE agent_thesis_lock SET claimed_at = ? "
            "WHERE thesis_id = ? AND accepted_at IS NULL AND claimed_at < ?",
            (now_ms, thesis_id, cutoff),
        )
        if cur.rowcount == 1:
            return {"acquired": True, "reason": "took_over_stale", "prior": None}
        row = conn.execute(
            "SELECT accepted_at, claimed_at FROM agent_thesis_lock WHERE thesis_id = ?",
            (thesis_id,),
        ).fetchone()
        if row is None:
            return {"acquired": True, "reason": "claimed", "prior": None}
        accepted_at, claimed_at = row[0], row[1]
        if accepted_at is not None:
            return {
                "acquired": False,
                "reason": "already_accepted",
                "prior": {"accepted_at": accepted_at},
            }
        return {
            "acquired": False,
            "reason": "in_flight",
            "prior": {"claimed_at": claimed_at},
        }
    finally:
        conn.close()


def release(thesis_id: str, *, accepted: bool) -> None:
    """Release claim.

    On accept: mark ``accepted_at`` (preserves row, blocks re-claim).
    On reject: delete row (allows corrected thesis to re-claim).
    """
    conn = _get_conn()
    try:
        if accepted:
            now_ms = int(time.time() * 1000)
            conn.execute(
                "UPDATE agent_thesis_lock SET accepted_at = ? WHERE thesis_id = ?",
                (now_ms, thesis_id),
            )
        else:
            conn.execute(
                "DELETE FROM agent_thesis_lock WHERE thesis_id = ? AND accepted_at IS NULL",
                (thesis_id,),
            )
    finally:
        conn.close()


def reset_for_tests() -> None:
    """Drop the lock table (test helper)."""
    conn = _get_conn()
    try:
        conn.execute("DROP TABLE IF EXISTS agent_thesis_lock")
    finally:
        conn.close()
