import unittest

from src.storage import batch as batch_module

from tests.storage_fakes import FakeCursor, FakePool


class BatchStorageTests(unittest.TestCase):
    def setUp(self):
        FakePool.reset()

    def test_start_batch_passes_parameters_and_returns_batch_id(self):
        cursor = FakeCursor(fetchone_result=(7,))
        FakePool.next_cursor = cursor

        batch_id = batch_module.start_batch(
            source="rss_news",
            data_type="news_articles",
            market="news",
            symbol="BTCUSDT",
            pool=FakePool(),
            quality_db_schema="quality",
        )

        self.assertEqual(7, batch_id)
        self.assertIn("quality.start_batch", cursor.execute_calls[0][0])
        self.assertEqual(
            ("rss_news", "news_articles", "news", "BTCUSDT", None, None),
            cursor.execute_calls[0][1],
        )

    def test_start_batch_returns_zero_on_database_error(self):
        cursor = FakeCursor(raise_on_execute=True)
        FakePool.next_cursor = cursor

        with self.assertRaises(RuntimeError):
            batch_module.start_batch(
                source="equity_poll",
                data_type="equity_1m",
                market="us_stock",
                pool=FakePool(),
                quality_db_schema="quality",
            )

    def test_start_batch_can_return_zero_when_explicitly_suppressed(self):
        cursor = FakeCursor(raise_on_execute=True)
        FakePool.next_cursor = cursor

        batch_id = batch_module.start_batch(
            source="equity_poll",
            data_type="equity_1m",
            market="us_stock",
            pool=FakePool(),
            quality_db_schema="quality",
            raise_on_error=False,
        )

        self.assertEqual(0, batch_id)


if __name__ == "__main__":
    unittest.main()
