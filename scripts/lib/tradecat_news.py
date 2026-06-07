#!/usr/bin/env python3
"""Read-only news query helpers for local TradeCat tooling."""

from __future__ import annotations

import csv
import io
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse, urlunparse


DEFAULT_NEWS_DATABASE_URL = "postgresql://postgres:postgres@localhost:5434/market_data"
DEFAULT_NEWS_DATABASE_SCHEMA = "alternative"
DEFAULT_NEWS_TABLE = "news_articles"
DEFAULT_NEWS_SOURCE = f"{DEFAULT_NEWS_DATABASE_SCHEMA}.{DEFAULT_NEWS_TABLE}"
MAX_NEWS_LIMIT = 200
MAX_SINCE_MINUTES = 60 * 24 * 30
_COMMON_QUOTE_SUFFIXES = ("USDT", "USD", "USDC", "BUSD", "FDUSD", "BTC", "ETH")


@dataclass(frozen=True)
class StoredNewsArticle:
    """Minimal stored news row returned by the read-only query."""

    dedup_hash: str
    published_at: float
    source: str
    url: str
    title: str
    summary: str
    symbols: tuple[str, ...]
    categories: tuple[str, ...]
    language: str


def _read_env_value(env_file: Path, key: str) -> str:
    try:
        lines = env_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""

    value = ""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        env_key, env_value = line.split("=", 1)
        env_key = env_key.strip()
        if env_key != key:
            continue
        env_value = env_value.strip()
        if env_value.startswith('"') and env_value.endswith('"') and len(env_value) >= 2:
            env_value = env_value[1:-1]
        elif env_value.startswith("'") and env_value.endswith("'") and len(env_value) >= 2:
            env_value = env_value[1:-1]
        else:
            comment_pos = env_value.find(" #")
            if comment_pos >= 0:
                env_value = env_value[:comment_pos].rstrip()
        value = env_value
    return value


def resolve_news_database_url(repo_root: Path, env: Mapping[str, str] | None = None) -> str:
    """Resolve the news database URL from env vars, config/.env, or the local default."""

    data = os.environ if env is None else env
    for key in ("TUI_NEWS_DATABASE_URL", "MARKETS_SERVICE_DATABASE_URL", "DATABASE_URL"):
        value = str(data.get(key, "") or "").strip()
        if value:
            return value

    env_file = repo_root / "config" / ".env"
    for key in ("TUI_NEWS_DATABASE_URL", "MARKETS_SERVICE_DATABASE_URL", "DATABASE_URL"):
        value = _read_env_value(env_file, key).strip()
        if value:
            return value
    return DEFAULT_NEWS_DATABASE_URL


def resolve_news_database_schema(repo_root: Path, env: Mapping[str, str] | None = None) -> str:
    """Resolve the news schema from env vars, config/.env, or the local default."""

    data = os.environ if env is None else env
    value = str(data.get("ALTERNATIVE_DB_SCHEMA", "") or "").strip()
    if value:
        return value

    env_file = repo_root / "config" / ".env"
    value = _read_env_value(env_file, "ALTERNATIVE_DB_SCHEMA").strip()
    if value:
        return value
    return DEFAULT_NEWS_DATABASE_SCHEMA


def clamp_limit(limit: int) -> int:
    """Clamp the requested limit to a safe range for local read-only tooling."""

    return max(1, min(int(limit), MAX_NEWS_LIMIT))


def clamp_since_minutes(since_minutes: int) -> int:
    """Clamp the lookback window to a bounded number of minutes."""

    return max(1, min(int(since_minutes), MAX_SINCE_MINUTES))


def _split_pipe(value: str) -> tuple[str, ...]:
    parts = [piece.strip() for piece in str(value or "").split("|")]
    return tuple(piece for piece in parts if piece)


def _build_netloc(parsed, port: int) -> str:
    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth = f"{auth}:{parsed.password}"
        auth = f"{auth}@"
    host = parsed.hostname or "localhost"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{auth}{host}:{int(port)}"


def _candidate_database_urls(db_url: str) -> list[str]:
    target = str(db_url or "").strip()
    if not target:
        return []

    candidates = [target]
    try:
        parsed = urlparse(target)
    except Exception:
        return candidates

    host = (parsed.hostname or "").strip().lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return candidates

    current_port = parsed.port or 5432
    for port in (5434, 5433, 5432):
        if port == current_port:
            continue
        candidate = urlunparse(parsed._replace(netloc=_build_netloc(parsed, port)))
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _is_connection_error(detail: str) -> bool:
    blob = (detail or "").lower()
    keys = (
        "connection to server at",
        "connection refused",
        "could not connect to server",
        "no route to host",
        "timeout expired",
    )
    return any(key in blob for key in keys)


def _normalize_symbol_term(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _symbol_search_terms(symbol_value: str) -> list[str]:
    raw = str(symbol_value or "").strip()
    if not raw:
        return []

    seen: set[str] = set()
    out: list[str] = []
    chunks = re.split(r"[\s,]+", raw)
    for chunk in chunks:
        if not chunk:
            continue

        candidates = {chunk}
        candidates.update(part for part in re.split(r"[-_./:]+", chunk) if part)
        if "." in chunk:
            base = chunk.split(".", 1)[0].strip()
            if base:
                candidates.add(base)

        for candidate in list(candidates):
            normalized = _normalize_symbol_term(candidate)
            if normalized:
                candidates.add(normalized)
                if len(normalized) > 4:
                    for suffix in _COMMON_QUOTE_SUFFIXES:
                        if normalized.endswith(suffix) and len(normalized) > len(suffix):
                            candidates.add(normalized[: -len(suffix)])
                if re.match(r"^(SH|SZ|HK|US)[A-Z0-9]+$", normalized) and len(normalized) > 2:
                    candidates.add(normalized[2:])

        for candidate in candidates:
            normalized = _normalize_symbol_term(candidate)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)

    return sorted(out)


def _sql_literal(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _sql_text_array(items: list[str]) -> str:
    escaped = ", ".join(_sql_literal(item) for item in items if item)
    return f"ARRAY[{escaped}]::text[]"


def _quote_sql_identifier(value: str, *, default: str) -> str:
    identifier = str(value or "").strip() or default
    escaped = identifier.replace(chr(34), chr(34) * 2)
    return f'"{escaped}"'


def _build_symbol_filter_sql(symbol_value: str) -> str:
    terms = _symbol_search_terms(symbol_value)
    if not terms:
        return ""

    return f"""
    AND EXISTS (
        SELECT 1
        FROM unnest(COALESCE(symbols, ARRAY[]::text[])) AS news_symbol(symbol_value)
        WHERE REGEXP_REPLACE(UPPER(news_symbol.symbol_value), '[^A-Z0-9]+', '', 'g') = ANY ({_sql_text_array(terms)})
    )
""".rstrip()


def _build_query_filter_sql(query: str) -> str:
    needle = str(query or "").strip()
    if not needle:
        return ""

    return f"""
    AND POSITION(
        LOWER({_sql_literal(needle)}) IN LOWER(
            CONCAT_WS(
                ' ',
                COALESCE(title, ''),
                COALESCE(summary, ''),
                COALESCE(source, ''),
                COALESCE(url, ''),
                COALESCE(array_to_string(symbols, ' '), ''),
                COALESCE(array_to_string(categories, ' '), '')
            )
        )
    ) > 0
""".rstrip()


def _build_filtered_copy_sql(
    *,
    limit: int,
    since_minutes: int,
    symbol: str,
    query: str,
    schema: str = DEFAULT_NEWS_DATABASE_SCHEMA,
) -> str:
    safe_limit = clamp_limit(limit)
    safe_since_minutes = clamp_since_minutes(since_minutes)
    symbol_filter = _build_symbol_filter_sql(symbol)
    query_filter = _build_query_filter_sql(query)
    schema_sql = _quote_sql_identifier(schema, default=DEFAULT_NEWS_DATABASE_SCHEMA)

    return f"""
COPY (
    SELECT
        dedup_hash,
        EXTRACT(EPOCH FROM published_at) AS published_at,
        COALESCE(source, '') AS source,
        COALESCE(url, '') AS url,
        COALESCE(title, '') AS title,
        COALESCE(summary, '') AS summary,
        COALESCE(array_to_string(symbols, '|'), '') AS symbols,
        COALESCE(array_to_string(categories, '|'), '') AS categories,
        COALESCE(language, 'en') AS language
    FROM {schema_sql}.{DEFAULT_NEWS_TABLE}
    WHERE published_at >= NOW() - INTERVAL '{safe_since_minutes} minutes'
{symbol_filter}
{query_filter}
    ORDER BY published_at DESC
    LIMIT {safe_limit}
) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)
""".strip()


def _build_recent_copy_sql(
    limit: int,
    window_hours: int,
    *,
    schema: str = DEFAULT_NEWS_DATABASE_SCHEMA,
) -> str:
    safe_limit = max(1, int(limit))
    safe_window_hours = max(1, int(window_hours))
    schema_sql = _quote_sql_identifier(schema, default=DEFAULT_NEWS_DATABASE_SCHEMA)

    return f"""
COPY (
    SELECT
        dedup_hash,
        EXTRACT(EPOCH FROM published_at) AS published_at,
        COALESCE(source, '') AS source,
        COALESCE(url, '') AS url,
        COALESCE(title, '') AS title,
        COALESCE(summary, '') AS summary,
        COALESCE(array_to_string(symbols, '|'), '') AS symbols,
        COALESCE(array_to_string(categories, '|'), '') AS categories,
        COALESCE(language, 'en') AS language
    FROM {schema_sql}.{DEFAULT_NEWS_TABLE}
    WHERE published_at >= NOW() - INTERVAL '{safe_window_hours} hours'
    ORDER BY published_at DESC
    LIMIT {safe_limit}
) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)
""".strip()


def _parse_article_rows(stdout: str) -> list[StoredNewsArticle]:
    reader = csv.DictReader(io.StringIO(stdout))
    rows: list[StoredNewsArticle] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        try:
            published_at = float(row.get("published_at") or 0.0)
        except Exception:
            published_at = 0.0
        if published_at <= 0:
            continue

        title = str(row.get("title") or "").strip()
        if not title:
            continue

        rows.append(
            StoredNewsArticle(
                dedup_hash=str(row.get("dedup_hash") or "").strip(),
                published_at=published_at,
                source=str(row.get("source") or "").strip(),
                url=str(row.get("url") or "").strip(),
                title=title,
                summary=str(row.get("summary") or "").strip(),
                symbols=_split_pipe(str(row.get("symbols") or "")),
                categories=_split_pipe(str(row.get("categories") or "")),
                language=str(row.get("language") or "en").strip() or "en",
            )
        )
    return rows


def _run_copy_query(db_url: str, *, sql: str, timeout_s: float, app_name: str) -> list[StoredNewsArticle]:
    target = str(db_url or "").strip()
    if not target:
        return []

    env = dict(os.environ)
    env.setdefault("PGAPPNAME", app_name)
    last_error = ""

    for candidate in _candidate_database_urls(target):
        cmd = [
            "psql",
            candidate,
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ]

        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(1.0, float(timeout_s)),
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            last_error = f"psql_timeout_{int(float(timeout_s))}s"
            raise RuntimeError(last_error) from exc
        except FileNotFoundError as exc:
            raise RuntimeError("psql_not_found") from exc

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or f"psql_exit_{proc.returncode}").strip()
            last_error = detail[:240] or f"psql_exit_{proc.returncode}"
            if _is_connection_error(last_error):
                continue
            raise RuntimeError(last_error)

        return _parse_article_rows(proc.stdout)

    raise RuntimeError(last_error or "psql_connection_failed")


def query_news_articles(
    db_url: str,
    *,
    symbol: str = "",
    query: str = "",
    limit: int = 20,
    since_minutes: int = 24 * 60,
    timeout_s: float = 5.0,
    schema: str = DEFAULT_NEWS_DATABASE_SCHEMA,
) -> list[StoredNewsArticle]:
    """Query recent news rows from TimescaleDB via `psql` and parse them into dataclasses."""

    sql = _build_filtered_copy_sql(
        limit=limit,
        since_minutes=since_minutes,
        symbol=symbol,
        query=query,
        schema=schema,
    )
    return _run_copy_query(db_url, sql=sql, timeout_s=timeout_s, app_name="tradecat_get_news")


def _news_item_matches_symbol(item_symbols: tuple[str, ...], title: str, summary: str, symbol_value: str) -> bool:
    terms = _symbol_search_terms(symbol_value)
    if not terms:
        return True
    blob = " ".join([*item_symbols, title, summary])
    upper_blob = blob.upper()
    normalized_blob = _normalize_symbol_term(blob)
    for term in terms:
        if term in normalized_blob or term in upper_blob:
            return True
        if len(term) >= 3 and term[:3] in upper_blob:
            return True
    return False


def _query_news_rss_fallback(
    repo_root: Path,
    *,
    symbol: str = "",
    query: str = "",
    limit: int = 20,
    since_minutes: int = 24 * 60,
    timeout_s: float = 5.0,
) -> list[StoredNewsArticle]:
    """Fetch news from built-in direct/RSS feeds when PostgreSQL is unavailable (same feeds as TUI)."""
    import sys
    import time

    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from tradecat.tui.news_defaults import CORE_TUI_NEWS_RSS_FEEDS
    from tradecat.tui.pages.news import RssNewsPoller

    # Core direct/RSS feeds only (fast); full TUI preset can be 700+ entries.
    feeds = list(CORE_TUI_NEWS_RSS_FEEDS)
    if not feeds:
        return []

    safe_limit = clamp_limit(limit)
    safe_since = clamp_since_minutes(since_minutes)
    poller = RssNewsPoller(
        feeds,
        timeout_s=max(12.0, float(timeout_s)),
        max_items=max(safe_limit * 8, 80),
        database_url="",
    )
    started = time.time()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TradeCat/1.0; +https://tradecat.local)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    items, _errors = poller._fetch_live_items(started, headers)  # noqa: SLF001 — shared with TUI poller
    cutoff = started - safe_since * 60
    needle = str(query or "").strip().lower()

    rows: list[StoredNewsArticle] = []
    for item in items:
        if float(item.published_at) < cutoff:
            continue
        title = str(item.title or "").strip()
        summary = str(item.summary or "").strip()
        if needle and needle not in f"{title} {summary}".lower():
            continue
        symbols = tuple(item.symbols or item.impact_assets or ())
        if not _news_item_matches_symbol(symbols, title, summary, symbol):
            continue
        rows.append(
            StoredNewsArticle(
                dedup_hash=str(item.id or ""),
                published_at=float(item.published_at),
                source=str(item.source or ""),
                url=str(item.url or ""),
                title=title,
                summary=summary,
                symbols=symbols,
                categories=(str(item.category or "").strip(),) if getattr(item, "category", "") else (),
                language="en",
            )
        )

    rows.sort(key=lambda row: row.published_at, reverse=True)
    return rows[:safe_limit]


def query_news_articles_with_fallback(
    repo_root: Path,
    db_url: str,
    *,
    symbol: str = "",
    query: str = "",
    limit: int = 20,
    since_minutes: int = 24 * 60,
    timeout_s: float = 5.0,
    schema: str = DEFAULT_NEWS_DATABASE_SCHEMA,
    allow_rss_fallback: bool = True,
) -> tuple[list[StoredNewsArticle], dict[str, object], list[str]]:
    """Try PostgreSQL first; on connection failure optionally fall back to live RSS/direct feeds."""
    warnings: list[str] = []
    table_name = f"{schema}.{DEFAULT_NEWS_TABLE}"
    try:
        rows = query_news_articles(
            db_url,
            symbol=symbol,
            query=query,
            limit=limit,
            since_minutes=since_minutes,
            timeout_s=timeout_s,
            schema=schema,
        )
        source = {
            "type": "postgresql",
            "table": table_name,
            "reader": "scripts/lib/tradecat_news.py",
            "writes": False,
        }
        return rows, source, warnings
    except RuntimeError as exc:
        detail = str(exc)
        if not allow_rss_fallback or not _is_connection_error(detail):
            raise
        warnings.append(f"postgresql_unavailable:{detail[:120]}")
        rows = _query_news_rss_fallback(
            repo_root,
            symbol=symbol,
            query=query,
            limit=limit,
            since_minutes=since_minutes,
            timeout_s=timeout_s,
        )
        source = {
            "type": "rss_fallback",
            "table": table_name,
            "reader": "tradecat.tui.pages.news.RssNewsPoller",
            "writes": False,
            "note": "PostgreSQL unreachable; served from built-in RSS/direct feeds",
        }
        return rows, source, warnings


def fetch_recent_news_articles(
    db_url: str,
    *,
    limit: int = 300,
    window_hours: int = 72,
    timeout_s: float = 5.0,
    schema: str = DEFAULT_NEWS_DATABASE_SCHEMA,
) -> list[StoredNewsArticle]:
    """Fetch recent news rows without symbol/query filters for UI consumers."""

    sql = _build_recent_copy_sql(limit=limit, window_hours=window_hours, schema=schema)
    return _run_copy_query(db_url, sql=sql, timeout_s=timeout_s, app_name="tradecat-tui-news")
