from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib import tradecat_news as _shared


StoredNewsArticle = _shared.StoredNewsArticle
DEFAULT_NEWS_DATABASE_URL = _shared.DEFAULT_NEWS_DATABASE_URL
DEFAULT_NEWS_DATABASE_SCHEMA = _shared.DEFAULT_NEWS_DATABASE_SCHEMA


def resolve_news_database_url(repo_root: Path, env: Mapping[str, str] | None = None) -> str:
    """Expose the shared read-only news DB URL resolver to TUI callers."""

    return _shared.resolve_news_database_url(repo_root, env=env)


def resolve_news_database_schema(repo_root: Path, env: Mapping[str, str] | None = None) -> str:
    """Expose the shared read-only news schema resolver to TUI callers."""

    return _shared.resolve_news_database_schema(repo_root, env=env)


def fetch_recent_news_articles(
    db_url: str,
    *,
    limit: int = 300,
    window_hours: int = 72,
    timeout_s: float = 5.0,
    schema: str = DEFAULT_NEWS_DATABASE_SCHEMA,
) -> list[StoredNewsArticle]:
    """Expose the shared read-only news fetcher to TUI callers."""

    return _shared.fetch_recent_news_articles(
        db_url,
        limit=limit,
        window_hours=window_hours,
        timeout_s=timeout_s,
        schema=schema,
    )
