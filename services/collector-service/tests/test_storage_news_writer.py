import unittest
from datetime import datetime, timezone

from src.storage import news_writer as news_writer_module

from tests.storage_fakes import FakeCursor, FakePool


class _Article(object):
    def __init__(
        self,
        dedup_hash="abc",
        source="J10",
        url="https://example.com/a",
        published_at=None,
        title="headline",
        summary="summary",
        content="content",
        symbols=None,
        categories=None,
        language="zh",
    ):
        self.dedup_hash = dedup_hash
        self.source = source
        self.url = url
        self.published_at = published_at or datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc)
        self.title = title
        self.summary = summary
        self.content = content
        self.symbols = symbols or ["BTC"]
        self.categories = categories or ["macro"]
        self.language = language


class NewsWriterTests(unittest.TestCase):
    def setUp(self):
        if hasattr(news_writer_module, "reset_shared_pool"):
            news_writer_module.reset_shared_pool()
        FakePool.reset()

    def _writer(self, cursor=None, **kwargs):
        FakePool.next_cursor = cursor or FakeCursor(rowcount=1)
        params = {
            "db_url": "postgresql://default/db",
            "default_db_url": "postgresql://default/db",
            "alternative_db_schema": "alternative",
            "retention_hours": 24,
            "cleanup_interval_s": 600,
            "pool_factory": FakePool,
        }
        params.update(kwargs)
        return news_writer_module.TimescaleNewsWriter(**params)

    def test_insert_articles_writes_dedup_insert_and_returns_rowcount(self):
        cursor = FakeCursor(rowcount=1)
        writer = self._writer(cursor=cursor)

        inserted = writer.insert_articles([_Article()], ingest_batch_id=7)

        self.assertEqual(1, inserted)
        self.assertIn('"alternative"."news_articles"', cursor.executemany_calls[0][0])
        self.assertIn("ON CONFLICT (dedup_hash) DO NOTHING", cursor.executemany_calls[0][0])
        self.assertEqual(7, cursor.executemany_calls[0][1][0][-1])

    def test_build_insert_values_normalizes_published_at_to_utc(self):
        writer = self._writer()
        article = _Article(published_at=datetime(2026, 3, 8, 8, 0))

        values = writer._build_insert_values([article], ingest_batch_id=9)

        self.assertEqual(datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc), values[0][3])

    def test_insert_articles_runs_cleanup_even_when_batch_is_empty(self):
        writer = self._writer()
        calls = []

        def fake_cleanup(now_monotonic=None):
            calls.append(now_monotonic)
            return 0

        writer._run_retention_cleanup = fake_cleanup

        inserted = writer.insert_articles([], ingest_batch_id=11)

        self.assertEqual(0, inserted)
        self.assertEqual([None], calls)

    def test_insert_articles_rejects_non_positive_batch_id(self):
        writer = self._writer()

        with self.assertRaises(ValueError):
            writer.insert_articles([_Article()], ingest_batch_id=0)

    def test_retention_cleanup_deletes_old_articles(self):
        cursor = FakeCursor(rowcount=2)
        writer = self._writer(cursor=cursor, cleanup_interval_s=60)
        writer._last_cleanup_monotonic = 0.0

        deleted = writer._run_retention_cleanup(now_monotonic=120.0)

        self.assertEqual(2, deleted)
        self.assertIn("DELETE FROM", cursor.execute_calls[0][0])
        self.assertIn('"alternative"."news_articles"', cursor.execute_calls[0][0])


if __name__ == "__main__":
    unittest.main()
