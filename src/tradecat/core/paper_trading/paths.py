"""Canonical paths for paper-trading SQLite storage."""
from __future__ import annotations

import os
from pathlib import Path


def resolve_paper_db_path(signal_db: str | Path) -> str:
    """Return paper DB path co-located with ``signal_history.db``."""
    path = Path(signal_db).expanduser().resolve()
    return str(path.parent / ".paper_trading.db")


def default_signal_db_path(repo_root: Path | None = None) -> Path:
    """Default ``signal_history.db`` under the TradeCat repo."""
    root = repo_root or find_tradeagnt_repo_root()
    return root / "libs" / "database" / "services" / "signal-service" / "signal_history.db"


def default_paper_db_path(repo_root: Path | None = None) -> str:
    """Default paper DB: beside ``signal_history.db``, or ``PAPER_DB_PATH`` env."""
    env = os.getenv("PAPER_DB_PATH", "").strip()
    if env:
        return str(Path(env).expanduser().resolve())
    return resolve_paper_db_path(default_signal_db_path(repo_root))


def find_tradeagnt_repo_root(start: Path | None = None) -> Path:
    cur = (start or Path(__file__)).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "libs" / "database").is_dir() and (
            (candidate / "AGENTS.md").is_file() or (candidate / "services").is_dir()
        ):
            return candidate
    return cur.parents[3]
