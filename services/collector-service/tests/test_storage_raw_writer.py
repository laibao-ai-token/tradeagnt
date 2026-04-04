import unittest
from datetime import datetime, timedelta

from src.storage import raw_writer as raw_writer_module

from tests.storage_fakes import FakeCursor, FakePool


class RawWriterTests(unittest.TestCase):
    def setUp(self):
        if hasattr(raw_writer_module, "reset_shared_pool"):
            raw_writer_module.reset_shared_pool()
        FakePool.reset()

    def test_upsert_kline_1m_writes_raw_table_with_legacy_field_mapping(self):
        cursor = FakeCursor(rowcount=1)
        FakePool.next_cursor = cursor
        writer = raw_writer_module.TimescaleRawWriter(
            db_url="postgresql://default/db",
            default_db_url="postgresql://default/db",
            raw_db_schema="raw",
            pool_factory=FakePool,
        )

        written = writer.upsert_kline_1m(
            [
                {
                    "exchange": "binance",
                    "symbol": "BTCUSDT",
                    "bucket_ts": 1774864800,
                    "trade_count": 8,
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 9.0,
                }
            ],
            ingest_batch_id=11,
        )

        self.assertEqual(1, written)
        self.assertIn('"raw"."crypto_kline_1m"', cursor.executemany_calls[0][0])
        self.assertIn("trades", cursor.executemany_calls[0][0])
        self.assertIn("ingest_batch_id = EXCLUDED.ingest_batch_id", cursor.executemany_calls[0][0])
        self.assertEqual(datetime.utcfromtimestamp(1774864800), cursor.executemany_calls[0][1][0][2])
        self.assertEqual(datetime.utcfromtimestamp(1774864800) + timedelta(minutes=1), cursor.executemany_calls[0][1][0][3])
        self.assertEqual(8, cursor.executemany_calls[0][1][0][10])
        self.assertEqual(11, cursor.executemany_calls[0][1][0][15])

    def test_upsert_metrics_5m_writes_raw_metrics_without_updated_at(self):
        cursor = FakeCursor(rowcount=1)
        FakePool.next_cursor = cursor
        writer = raw_writer_module.TimescaleRawWriter(
            db_url="postgresql://default/db",
            default_db_url="postgresql://default/db",
            raw_db_schema="raw",
            pool_factory=FakePool,
        )

        written = writer.upsert_metrics_5m(
            [
                {
                    "exchange": "binance",
                    "symbol": "BTCUSDT",
                    "create_time": 1774865100,
                    "sum_open_interest": 123.0,
                    "sum_open_interest_value": 456.0,
                    "count_long_short_ratio": 1.1,
                    "count_toptrader_long_short_ratio": 1.2,
                    "sum_taker_long_short_vol_ratio": 0.8,
                }
            ],
            ingest_batch_id=13,
        )

        self.assertEqual(1, written)
        self.assertIn('"raw"."crypto_metrics_5m"', cursor.executemany_calls[0][0])
        self.assertNotIn("updated_at = NOW()", cursor.executemany_calls[0][0])
        self.assertEqual(datetime.utcfromtimestamp(1774865100), cursor.executemany_calls[0][1][0][2])
        self.assertEqual(123.0, cursor.executemany_calls[0][1][0][3])
        self.assertEqual(456.0, cursor.executemany_calls[0][1][0][4])
        self.assertEqual(1.1, cursor.executemany_calls[0][1][0][5])
        self.assertEqual(1.2, cursor.executemany_calls[0][1][0][6])
        self.assertEqual(0.8, cursor.executemany_calls[0][1][0][7])
        self.assertEqual(13, cursor.executemany_calls[0][1][0][9])

    def test_upsert_equity_1m_uses_market_table_and_defaults_close_time(self):
        cursor = FakeCursor(rowcount=1)
        FakePool.next_cursor = cursor
        writer = raw_writer_module.TimescaleRawWriter(
            db_url="postgresql://default/db",
            default_db_url="postgresql://default/db",
            raw_db_schema="raw",
            pool_factory=FakePool,
        )

        written = writer.upsert_equity_1m(
            "us_stock",
            [
                {
                    "exchange": "nasdaq",
                    "symbol": "NVDA",
                    "open_time": 1774864800,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000,
                }
            ],
            ingest_batch_id=21,
            source="equity_poll",
        )

        self.assertEqual(1, written)
        self.assertIn('"raw"."us_equity_1m"', cursor.executemany_calls[0][0])
        self.assertIn("ingest_batch_id = EXCLUDED.ingest_batch_id", cursor.executemany_calls[0][0])
        self.assertEqual(datetime.utcfromtimestamp(1774864800), cursor.executemany_calls[0][1][0][2])
        self.assertEqual(datetime.utcfromtimestamp(1774864800) + timedelta(minutes=1), cursor.executemany_calls[0][1][0][3])
        self.assertEqual(21, cursor.executemany_calls[0][1][0][11])

    def test_upsert_equity_1m_rejects_unknown_market(self):
        writer = raw_writer_module.TimescaleRawWriter(
            db_url="postgresql://default/db",
            default_db_url="postgresql://default/db",
            raw_db_schema="raw",
            pool_factory=FakePool,
        )

        with self.assertRaises(ValueError):
            writer.upsert_equity_1m("broken", [], ingest_batch_id=1, source="equity_poll")

    def test_upsert_kline_1m_rejects_non_positive_batch_id(self):
        writer = raw_writer_module.TimescaleRawWriter(
            db_url="postgresql://default/db",
            default_db_url="postgresql://default/db",
            raw_db_schema="raw",
            pool_factory=FakePool,
        )

        with self.assertRaises(ValueError):
            writer.upsert_kline_1m([], ingest_batch_id=0)


if __name__ == "__main__":
    unittest.main()
