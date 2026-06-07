"""Shared PaperTradingEngine factory for agent module."""
from __future__ import annotations

import os

from tradecat.core.paper_trading.engine import PaperTradingEngine

_cached_engine: PaperTradingEngine | None = None


def get_paper_engine() -> PaperTradingEngine:
    """Return a cached PaperTradingEngine instance (singleton per process)."""
    global _cached_engine
    if _cached_engine is not None:
        return _cached_engine
    repo_type = os.getenv("PAPER_REPO_TYPE", "sqlite")
    if repo_type == "memory":
        from tradecat.core.paper_trading import InMemoryRepository

        _cached_engine = PaperTradingEngine(InMemoryRepository())
    else:
        from tradecat.core.paper_trading.paths import default_paper_db_path
        from tradecat.core.paper_trading.repository import SqliteRepository

        _cached_engine = PaperTradingEngine(SqliteRepository(db_path=default_paper_db_path()))
    return _cached_engine
