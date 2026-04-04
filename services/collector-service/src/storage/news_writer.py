"""News article writer for collector-service."""

from __future__ import absolute_import

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence, Tuple

from src.config import load_config
from src.storage.timescale import TimescaleStorage, reset_shared_pool

logger = logging.getLogger(__name__)

UTC = timezone.utc


def _validate_identifier(value, label):
    # type: (str, str) -> str
    text = (value or "").strip()
    if not text:
        raise ValueError("Missing {0}".format(label))
    first = text[0]
    if not (first.isalpha() or first == "_"):
        raise ValueError("Invalid {0}: {1}".format(label, value))
    for char in text[1:]:
        if not (char.isalnum() or char == "_"):
            raise ValueError("Invalid {0}: {1}".format(label, value))
    return text


def _article_value(article, field, default=None):
    # type: (Any, str, Any) -> Any
    if isinstance(article, dict):
        return article.get(field, default)
    return getattr(article, field, default)


def _require_positive_batch_id(value):
    # type: (Any) -> int
    batch_id = int(value)
    if batch_id <= 0:
        raise ValueError("ingest_batch_id must be positive")
    return batch_id


class TimescaleNewsWriter(TimescaleStorage):
    """Write deduplicated news rows into alternative.news_articles."""

    def __init__(
        self,
        db_url=None,
        default_db_url=None,
        alternative_db_schema=None,
        retention_hours=None,
        cleanup_interval_s=None,
        pool_factory=None,
    ):
        # type: (Optional[str], Optional[str], Optional[str], Optional[int], Optional[int], Optional[Any]) -> None
        cfg = load_config()
        super(TimescaleNewsWriter, self).__init__(
            db_url=db_url,
            default_db_url=default_db_url,
            pool_factory=pool_factory,
        )
        self.schema = _validate_identifier(alternative_db_schema or cfg.database.alternative_db_schema, "schema")
        self._retention_hours = max(0, int(retention_hours if retention_hours is not None else cfg.news.retention_hours))
        cleanup_value = cleanup_interval_s if cleanup_interval_s is not None else cfg.news.retention_cleanup_interval_seconds
        self._cleanup_interval_s = max(60, int(cleanup_value))
        self._last_cleanup_monotonic = 0.0

    def _build_insert_values(self, articles, ingest_batch_id):
        # type: (Sequence[Any], int) -> List[Tuple[Any, ...]]
        batch_id = _require_positive_batch_id(ingest_batch_id)
        values = []
        for article in articles:
            published_at = _article_value(article, "published_at")
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            else:
                published_at = published_at.astimezone(UTC)
            values.append(
                (
                    _article_value(article, "dedup_hash"),
                    _article_value(article, "source"),
                    _article_value(article, "url"),
                    published_at,
                    _article_value(article, "title"),
                    _article_value(article, "summary"),
                    _article_value(article, "content"),
                    _article_value(article, "symbols") or None,
                    _article_value(article, "categories") or None,
                    _article_value(article, "language", "en") or "en",
                    batch_id,
                )
            )
        return values

    def _insert_article_batch(self, articles, ingest_batch_id):
        # type: (Sequence[Any], int) -> int
        if not articles:
            return 0

        columns = [
            "dedup_hash",
            "source",
            "url",
            "published_at",
            "title",
            "summary",
            "content",
            "symbols",
            "categories",
            "language",
            "ingest_batch_id",
        ]
        query = (
            'INSERT INTO "{schema}"."news_articles" ({columns}) '
            "VALUES ({placeholders}) "
            "ON CONFLICT (dedup_hash) DO NOTHING"
        ).format(
            schema=self.schema,
            columns=", ".join(['"{0}"'.format(column) for column in columns]),
            placeholders=", ".join(["%s"] * len(columns)),
        )
        values = self._build_insert_values(articles, ingest_batch_id)
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, values)
                inserted = int(cur.rowcount or 0)
                conn.commit()
        return inserted

    def _should_run_retention_cleanup(self, now_monotonic=None):
        # type: (Optional[float]) -> bool
        if self._retention_hours <= 0:
            return False
        current = time.monotonic() if now_monotonic is None else float(now_monotonic)
        return (current - self._last_cleanup_monotonic) >= self._cleanup_interval_s

    def _run_retention_cleanup(self, now_monotonic=None):
        # type: (Optional[float]) -> int
        current = time.monotonic() if now_monotonic is None else float(now_monotonic)
        if not self._should_run_retention_cleanup(current):
            return 0

        self._last_cleanup_monotonic = current
        cutoff = datetime.now(tz=UTC) - timedelta(hours=self._retention_hours)
        query = 'DELETE FROM "{schema}"."news_articles" WHERE published_at < %s'.format(schema=self.schema)
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (cutoff,))
                    deleted = int(cur.rowcount or 0)
                    conn.commit()
        except Exception as exc:
            logger.warning("news retention cleanup failed: hours=%s error=%s", self._retention_hours, exc)
            return 0
        if deleted > 0:
            logger.info("news retention cleanup: deleted=%d older_than=%sh", deleted, self._retention_hours)
        return deleted

    def insert_articles(self, articles, ingest_batch_id):
        # type: (Sequence[Any], int) -> int
        inserted = self._insert_article_batch(articles, ingest_batch_id)
        self._run_retention_cleanup()
        return inserted
