#!/usr/bin/python3.12
"""Poll RSS/direct feeds and upsert into alternative.news_articles (PostgreSQL)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.lib.tradecat_news import _candidate_database_urls
from tradecat.tui.news_db import resolve_news_database_schema, resolve_news_database_url
from tradecat.tui.news_defaults import CORE_TUI_NEWS_RSS_FEEDS, default_tui_news_rss_feeds_value
from tradecat.tui.pages.news import NewsItem, RssNewsPoller, _parse_rss_feeds_value


def _resolve_feeds() -> list[str]:
    raw = (os.getenv("NEWS_RSS_FEEDS") or os.getenv("TUI_NEWS_RSS_FEEDS") or "").strip()
    if raw:
        return _parse_rss_feeds_value(raw)
    preset = (os.getenv("TUI_NEWS_RSS_PRESET") or os.getenv("NEWS_RSS_PRESET") or "core").strip().lower()
    if preset in ("core", ""):
        return list(CORE_TUI_NEWS_RSS_FEEDS)
    return list(default_tui_news_rss_feeds_value())


def _sql_literal(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _array_literal(values: tuple[str, ...]) -> str:
    if not values:
        return "ARRAY[]::text[]"
    parts = [_sql_literal(v) for v in values if str(v).strip()]
    return "ARRAY[" + ",".join(parts) + "]::text[]"


def _resolve_working_db_url(db_url: str) -> str:
    for candidate in _candidate_database_urls(db_url):
        proc = subprocess.run(
            ["psql", candidate, "-X", "-q", "-c", "SELECT 1"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return candidate
    return db_url


def _upsert_items(db_url: str, schema: str, items: list[NewsItem]) -> int:
    if not items:
        return 0
    db_url = _resolve_working_db_url(db_url)
    schema_sql = schema.strip() or "alternative"
    written = 0
    for item in items:
        dedup = (item.id or "").strip()
        if not dedup:
            continue
        title = (item.title or "").strip()
        if not title:
            continue
        try:
            published = datetime.fromtimestamp(float(item.published_at), tz=timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)
        symbols = tuple(item.symbols or item.impact_assets or ())
        categories = tuple(filter(None, [item.category, f"tc_source_group:{item.source_group}", f"tc_source_tier:{item.source_tier}"]))
        sql = f"""
INSERT INTO {schema_sql}.news_articles (
  dedup_hash, published_at, source, url, title, summary, symbols, categories, language, fetched_at
) VALUES (
  {_sql_literal(dedup)},
  {_sql_literal(published.isoformat())}::timestamptz,
  {_sql_literal(item.source)},
  {_sql_literal(item.url)},
  {_sql_literal(title)},
  {_sql_literal(item.summary or title)},
  {_array_literal(symbols)},
  {_array_literal(categories)},
  {_sql_literal('zh' if any(ord(c) > 127 for c in title) else 'en')},
  NOW()
)
ON CONFLICT (dedup_hash) DO UPDATE SET
  fetched_at = NOW(),
  title = EXCLUDED.title,
  summary = EXCLUDED.summary,
  url = EXCLUDED.url;
""".strip()
        proc = subprocess.run(
            ["psql", db_url, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            written += 1
    return written


def main() -> int:
    feeds = _resolve_feeds()
    if not feeds:
        print("no feeds configured", file=sys.stderr)
        return 1

    db_url = resolve_news_database_url(ROOT)
    schema = resolve_news_database_schema(ROOT)
    try:
        interval = float(os.getenv("NEWS_RSS_POLL_INTERVAL_SECONDS", "30").strip() or "30")
    except Exception:
        interval = 30.0
    interval = max(10.0, interval)

    # Headless poller: fetch only, no DB read in loop.
    poller = RssNewsPoller(
        feeds,
        refresh_s=interval,
        timeout_s=float(os.getenv("NEWS_RSS_TIMEOUT_SECONDS", "20").strip() or "20"),
        max_items=int(os.getenv("NEWS_RSS_LIMIT", "200").strip() or "200"),
        database_url="",
    )
    print(f"[news-sync] db={db_url} schema={schema} feeds={len(feeds)} interval={interval}s")
    while True:
        started = time.time()
        try:
            poller._refresh_once(started=started)
            snap = poller.snapshot()
            n = _upsert_items(db_url, schema, list(snap.items))
            latest = ""
            if snap.latest_item_at > 0:
                latest = datetime.fromtimestamp(snap.latest_item_at).strftime("%H:%M:%S")
            print(
                f"[news-sync] {datetime.now().strftime('%H:%M:%S')} "
                f"items={len(snap.items)} upserted={n} latest={latest} err={snap.last_error or '-'}",
                flush=True,
            )
        except Exception as exc:
            print(f"[news-sync] error: {exc}", file=sys.stderr, flush=True)
        elapsed = time.time() - started
        time.sleep(max(1.0, interval - elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
