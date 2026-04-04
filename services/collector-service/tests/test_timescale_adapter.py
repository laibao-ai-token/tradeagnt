import unittest
from datetime import datetime, timedelta

from src.adapters import timescale as timescale_module
from tests.storage_fakes import render_query_text


class _FakeCopy(object):
    def __init__(self, cursor, query):
        self._cursor = cursor
        self._query = query
        self.rows = []

    def __enter__(self):
        self._cursor.copy_queries.append(self._query)
        self._cursor.copy_batches.append(self.rows)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write_row(self, row):
        self.rows.append(tuple(row))


class _FakeCursor(object):
    def __init__(self, fetchone_result=None, fetchall_result=None):
        self.execute_calls = []
        self.copy_queries = []
        self.copy_batches = []
        self.rowcount = 0
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        text = render_query_text(query)
        self.execute_calls.append((text, params))
        if "start_batch" in text:
            self.rowcount = 1
        else:
            self.rowcount = 0

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return list(self._fetchall_result)

    def copy(self, query):
        return _FakeCopy(self, render_query_text(query))


class _FakeConnection(object):
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commit_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):
        del row_factory
        return self.cursor_obj

    def commit(self):
        self.commit_calls += 1


class _FakePool(object):
    created = []
    next_cursor = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        cursor = self.__class__.next_cursor or _FakeCursor()
        self.connection_obj = _FakeConnection(cursor)
        self.closed = False
        self.__class__.created.append(self)

    def connection(self):
        return self.connection_obj

    def close(self):
        self.closed = True

    @classmethod
    def reset(cls):
        cls.created = []
        cls.next_cursor = None


class TimescaleAdapterTests(unittest.TestCase):
    def setUp(self):
        if hasattr(timescale_module, "reset_shared_pool"):
            timescale_module.reset_shared_pool()
        _FakePool.reset()

    def _adapter(self, **kwargs):
        params = {
            "db_url": "postgresql://default/db",
            "default_db_url": "postgresql://default/db",
            "market_db_schema": "market_data",
            "raw_db_schema": "raw",
            "quality_db_schema": "quality",
            "write_mode": "legacy",
            "pool_factory": _FakePool,
        }
        params.update(kwargs)
        return timescale_module.TimescaleAdapter(**params)

    def test_shared_pool_is_reused_for_default_database_url(self):
        adapter_a = self._adapter()
        adapter_b = self._adapter()

        self.assertIs(adapter_a.pool, adapter_b.pool)
        self.assertEqual(1, len(_FakePool.created))

    def test_non_default_database_url_uses_private_pool(self):
        adapter_a = self._adapter(db_url="postgresql://custom-a/db", default_db_url="postgresql://default/db")
        adapter_b = self._adapter(db_url="postgresql://custom-b/db", default_db_url="postgresql://default/db")

        self.assertIsNot(adapter_a.pool, adapter_b.pool)
        self.assertEqual(2, len(_FakePool.created))

    def test_upsert_candles_legacy_uses_copy_pipeline(self):
        cursor = _FakeCursor()
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="legacy")

        written = adapter.upsert_candles(
            "1m",
            [
                {
                    "exchange": "binance",
                    "symbol": "BTCUSDT",
                    "bucket_ts": datetime(2026, 3, 30, 10, 0, 0),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.5,
                    "close": 100.5,
                    "volume": 12.0,
                }
            ],
        )

        self.assertEqual(1, written)
        self.assertIn("CREATE TEMP TABLE", cursor.execute_calls[0][0])
        self.assertIn('"market_data"."candles_1m"', cursor.execute_calls[0][0])
        self.assertIn("COPY", cursor.copy_queries[0])
        self.assertIn("bucket_ts", cursor.copy_queries[0])
        self.assertIn('ON CONFLICT ("exchange", "symbol", "bucket_ts")', cursor.execute_calls[-1][0])

    def test_upsert_candles_legacy_batches_copy_work_by_batch_size(self):
        cursor = _FakeCursor()
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="legacy")

        rows = []
        for minute in range(3):
            rows.append(
                {
                    "exchange": "binance",
                    "symbol": "BTCUSDT",
                    "bucket_ts": datetime(2026, 3, 30, 10, minute, 0),
                    "open": 100.0 + minute,
                    "high": 101.0 + minute,
                    "low": 99.5 + minute,
                    "close": 100.5 + minute,
                    "volume": 12.0 + minute,
                }
            )

        written = adapter.upsert_candles("1m", rows, batch_size=2)

        self.assertEqual(3, written)
        self.assertEqual(2, len(cursor.copy_batches))
        self.assertEqual(2, len(cursor.copy_batches[0]))
        self.assertEqual(1, len(cursor.copy_batches[1]))
        self.assertEqual(2, len(cursor.execute_calls))
        self.assertIn("CREATE TEMP TABLE", cursor.execute_calls[0][0])
        self.assertIn("INSERT INTO", cursor.execute_calls[1][0])

    def test_upsert_candles_raw_transforms_rows_and_fetches_batch_id(self):
        cursor = _FakeCursor(fetchone_result=(7,))
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="raw")

        written = adapter.upsert_candles(
            "1m",
            [
                {
                    "exchange": "binance",
                    "symbol": "ETHUSDT",
                    "bucket_ts": 1774864800,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 20.0,
                }
            ],
        )

        self.assertEqual(1, written)
        self.assertIn("start_batch", cursor.execute_calls[0][0])
        self.assertEqual(("collector-service", "kline", "crypto", None, None, None), cursor.execute_calls[0][1])
        self.assertIn('"raw"."crypto_kline_1m"', cursor.execute_calls[-2][0])
        self.assertEqual(16, len(cursor.copy_batches[0][0]))
        self.assertEqual(datetime.utcfromtimestamp(1774864800), cursor.copy_batches[0][0][2])
        self.assertEqual(
            datetime.utcfromtimestamp(1774864800) + timedelta(minutes=1),
            cursor.copy_batches[0][0][3],
        )
        self.assertEqual(7, cursor.copy_batches[0][0][-1])

    def test_upsert_metrics_raw_transforms_rows(self):
        cursor = _FakeCursor(fetchone_result=(9,))
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="raw")

        written = adapter.upsert_metrics(
            [
                {
                    "symbol": "BTCUSDT",
                    "create_time": 1774865100,
                    "sumOpenInterest": 123.0,
                    "sumOpenInterestValue": 456.0,
                    "long_short_ratio": 1.2,
                    "topAccountLongShortRatio": 1.3,
                    "takerBuySellRatio": 0.9,
                }
            ]
        )

        self.assertEqual(1, written)
        self.assertEqual(("collector-service", "metrics", "crypto", None, None, None), cursor.execute_calls[0][1])
        self.assertIn('"raw"."crypto_metrics_5m"', cursor.execute_calls[-2][0])
        self.assertEqual(10, len(cursor.copy_batches[0][0]))
        self.assertEqual(datetime.utcfromtimestamp(1774865100), cursor.copy_batches[0][0][2])
        self.assertEqual(9, cursor.copy_batches[0][0][-1])

    def test_upsert_metrics_raw_accepts_legacy_snake_case_fields(self):
        cursor = _FakeCursor(fetchone_result=(13,))
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="raw")

        written = adapter.upsert_metrics(
            [
                {
                    "symbol": "BTCUSDT",
                    "create_time": datetime(2026, 3, 30, 10, 5, 0),
                    "sum_open_interest": 123.0,
                    "sum_open_interest_value": 456.0,
                    "count_long_short_ratio": 1.1,
                    "count_toptrader_long_short_ratio": 1.2,
                    "sum_taker_long_short_vol_ratio": 0.8,
                }
            ]
        )

        self.assertEqual(1, written)
        self.assertEqual(123.0, cursor.copy_batches[0][0][3])
        self.assertEqual(456.0, cursor.copy_batches[0][0][4])
        self.assertEqual(1.1, cursor.copy_batches[0][0][5])
        self.assertEqual(1.2, cursor.copy_batches[0][0][6])
        self.assertEqual(0.8, cursor.copy_batches[0][0][7])
        self.assertEqual(13, cursor.copy_batches[0][0][9])

    def test_upsert_metrics_raw_does_not_force_updated_at_assignment(self):
        cursor = _FakeCursor(fetchone_result=(5,))
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="raw")

        adapter.upsert_metrics(
            [
                {
                    "symbol": "BTCUSDT",
                    "create_time": datetime(2026, 3, 30, 10, 5, 0),
                    "sum_open_interest": 1.0,
                }
            ]
        )

        self.assertNotIn("updated_at = NOW()", cursor.execute_calls[-1][0])

    def test_upsert_candles_raw_maps_trade_count_to_trades(self):
        cursor = _FakeCursor(fetchone_result=(4,))
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="raw")

        adapter.upsert_candles(
            "1m",
            [
                {
                    "exchange": "binance",
                    "symbol": "BTCUSDT",
                    "bucket_ts": datetime(2026, 3, 30, 10, 0, 0),
                    "trade_count": 8,
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 9.0,
                }
            ],
        )

        self.assertEqual(8, cursor.copy_batches[0][0][10])

    def test_raw_mode_rejects_non_1m_kline_interval(self):
        adapter = self._adapter(write_mode="raw")

        with self.assertRaises(ValueError):
            adapter.upsert_candles(
                "5m",
                [
                    {
                        "exchange": "binance",
                        "symbol": "BTCUSDT",
                        "bucket_ts": datetime(2026, 3, 30, 10, 0, 0),
                        "open": 1.0,
                        "high": 2.0,
                        "low": 0.5,
                        "close": 1.5,
                    }
                ],
            )

    def test_get_symbols_uses_parameterized_query(self):
        cursor = _FakeCursor(fetchall_result=[("BTCUSDT",), ("ETHUSDT",)])
        _FakePool.next_cursor = cursor
        adapter = self._adapter()

        symbols = adapter.get_symbols("binance", "1m")

        self.assertEqual(["BTCUSDT", "ETHUSDT"], symbols)
        self.assertIn("WHERE exchange = %s", cursor.execute_calls[-1][0])
        self.assertEqual(("binance",), cursor.execute_calls[-1][1])

    def test_get_symbols_raw_mode_reads_from_raw_crypto_kline_table(self):
        cursor = _FakeCursor(fetchall_result=[("BTCUSDT",)])
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="raw")

        symbols = adapter.get_symbols("binance", "1m")

        self.assertEqual(["BTCUSDT"], symbols)
        self.assertIn('"raw"."crypto_kline_1m"', cursor.execute_calls[-1][0])

    def test_detect_gaps_raw_mode_uses_open_time_field(self):
        cursor = _FakeCursor(fetchall_result=[("BTCUSDT",)])
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="raw")

        adapter.detect_gaps("binance", "1m", ["BTCUSDT"])

        self.assertIn('"raw"."crypto_kline_1m"', cursor.execute_calls[-1][0])
        self.assertIn("open_time", cursor.execute_calls[-1][0])
        self.assertNotIn("bucket_ts", cursor.execute_calls[-1][0])

    def test_query_raw_mode_uses_open_time_field(self):
        cursor = _FakeCursor(fetchall_result=[{"symbol": "BTCUSDT"}])
        _FakePool.next_cursor = cursor
        adapter = self._adapter(write_mode="raw")

        rows = adapter.query(
            "binance",
            "BTCUSDT",
            "1m",
            start=datetime(2026, 3, 30, 10, 0, 0),
            end=datetime(2026, 3, 30, 10, 1, 0),
        )

        self.assertEqual([{"symbol": "BTCUSDT"}], rows)
        self.assertIn('"raw"."crypto_kline_1m"', cursor.execute_calls[-1][0])
        self.assertIn("open_time >=", cursor.execute_calls[-1][0])
        self.assertIn("open_time <=", cursor.execute_calls[-1][0])
        self.assertIn("ORDER BY open_time DESC", cursor.execute_calls[-1][0])

    def test_detect_gaps_rejects_interval_sql_injection(self):
        adapter = self._adapter()

        with self.assertRaises(ValueError):
            adapter.detect_gaps("binance", "1m; DROP TABLE raw.crypto_kline_1m", ["BTCUSDT"])


if __name__ == "__main__":
    unittest.main()
