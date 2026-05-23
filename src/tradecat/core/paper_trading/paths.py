"""Canonical paths for paper-trading SQLite storage."""
from __future__ import annotations

import os
from pathlib import Path

_LEGACY_REL = Path("libs/database/services/signal-service/signal_history.db")
_DATA_REL = Path("data/signal_history.db")


def resolve_paper_db_path(signal_db: str | Path) -> str:
    """Return paper DB path co-located with ``signal_history.db``."""
    path = Path(signal_db).expanduser().resolve()
    return str(path.parent / ".paper_trading.db")


def default_data_dir(repo_root: Path | None = None) -> Path:
    """Directory for tradeagnt-local SQLite (``data/`` by default)."""
    env = os.getenv("TRADEAGNT_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    root = repo_root or find_tradeagnt_repo_root()
    return root / "data"


def default_signal_db_path(repo_root: Path | None = None) -> Path:
    """Resolve ``signal_history.db``: env > ``data/`` > legacy ``libs/...``."""
    env = os.getenv("SIGNAL_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()

    root = repo_root or find_tradeagnt_repo_root()
    data_path = default_data_dir(root) / "signal_history.db"
    legacy_path = root / _LEGACY_REL

    if data_path.is_file():
        return data_path
    if legacy_path.is_file():
        return legacy_path
    return data_path


def default_paper_db_path(repo_root: Path | None = None) -> str:
    """Default paper DB: beside ``signal_history.db``, or ``PAPER_DB_PATH`` env."""
    env = os.getenv("PAPER_DB_PATH", "").strip()
    if env:
        return str(Path(env).expanduser().resolve())
    return resolve_paper_db_path(default_signal_db_path(repo_root))


def find_tradeagnt_repo_root(start: Path | None = None) -> Path:
    """Locate repo root (tradeagnt monolith; no ``services/`` required)."""
    cur = (start or Path(__file__)).resolve()
    for candidate in [cur, *cur.parents]:
        if not (candidate / "AGENTS.md").is_file():
            continue
        if (candidate / "src" / "tradecat").is_dir():
            return candidate
        if (candidate / "data").is_dir() or (candidate / "libs" / "database").is_dir():
            return candidate
    return cur.parents[3]


find_project_root = find_tradeagnt_repo_root


def legacy_signal_db_path(repo_root: Path | None = None) -> Path:
    """Fork-era default path (for migration only)."""
    root = repo_root or find_tradeagnt_repo_root()
    return root / _LEGACY_REL
