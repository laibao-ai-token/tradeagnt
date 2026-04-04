import unittest
from datetime import datetime, timedelta

from src.adapters import schema_adapter as schema_module


class SchemaAdapterTests(unittest.TestCase):
    def test_raw_mode_uses_raw_tables_and_conflict_keys(self):
        adapter = schema_module.SchemaAdapter(
            write_mode="raw",
            market_db_schema="market_data",
            raw_db_schema="raw",
        )

        self.assertEqual("raw.crypto_kline_1m", adapter.get_kline_table("1m"))
        self.assertEqual("raw.crypto_metrics_5m", adapter.get_metrics_table())
        self.assertEqual(("exchange", "symbol", "open_time"), adapter.get_kline_conflict_keys())
        self.assertEqual(("exchange", "symbol", "timestamp"), adapter.get_metrics_conflict_keys())
        self.assertEqual("open_time", adapter.get_kline_time_field())
        self.assertEqual("timestamp", adapter.get_metrics_time_field())

    def test_legacy_mode_uses_market_tables_and_conflict_keys(self):
        adapter = schema_module.SchemaAdapter(
            write_mode="legacy",
            market_db_schema="market_data",
            raw_db_schema="raw",
        )

        self.assertEqual("market_data.candles_5m", adapter.get_kline_table("5m"))
        self.assertEqual("market_data.binance_futures_metrics_5m", adapter.get_metrics_table())
        self.assertEqual(("exchange", "symbol", "bucket_ts"), adapter.get_kline_conflict_keys())
        self.assertEqual(("symbol", "create_time"), adapter.get_metrics_conflict_keys())
        self.assertEqual("bucket_ts", adapter.get_kline_time_field())
        self.assertEqual("create_time", adapter.get_metrics_time_field())

    def test_kline_adapter_maps_legacy_fields_to_raw_schema(self):
        rows = schema_module.KlineAdapter.to_new_schema(
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
                }
            ],
            batch_id=11,
            interval="1m",
        )

        self.assertEqual(datetime(2026, 3, 30, 10, 0, 0), rows[0]["open_time"])
        self.assertEqual(datetime(2026, 3, 30, 10, 1, 0), rows[0]["close_time"])
        self.assertEqual(8, rows[0]["trades"])
        self.assertEqual(11, rows[0]["ingest_batch_id"])

    def test_kline_adapter_normalizes_epoch_timestamps_to_utc(self):
        rows = schema_module.KlineAdapter.to_new_schema(
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
                }
            ],
            batch_id=11,
            interval="1m",
        )

        self.assertEqual(datetime.utcfromtimestamp(1774864800), rows[0]["open_time"])
        self.assertEqual(datetime.utcfromtimestamp(1774864800) + timedelta(minutes=1), rows[0]["close_time"])

    def test_kline_adapter_roundtrip_drops_raw_only_fields(self):
        rows = schema_module.KlineAdapter.to_legacy_schema(
            [
                {
                    "exchange": "binance",
                    "symbol": "BTCUSDT",
                    "open_time": datetime(2026, 3, 30, 10, 0, 0),
                    "close_time": datetime(2026, 3, 30, 10, 1, 0),
                    "trades": 9,
                    "ingest_batch_id": 3,
                    "ingested_at": datetime(2026, 3, 30, 10, 2, 0),
                }
            ]
        )

        self.assertEqual(datetime(2026, 3, 30, 10, 0, 0), rows[0]["bucket_ts"])
        self.assertEqual(9, rows[0]["trade_count"])
        self.assertNotIn("close_time", rows[0])
        self.assertNotIn("ingest_batch_id", rows[0])

    def test_metrics_adapter_maps_legacy_fields_to_raw_schema(self):
        rows = schema_module.MetricsAdapter.to_new_schema(
            [
                {
                    "symbol": "BTCUSDT",
                    "create_time": datetime(2026, 3, 30, 10, 5, 0),
                    "sum_open_interest": 123.0,
                    "sum_open_interest_value": 456.0,
                    "count_toptrader_long_short_ratio": 1.3,
                    "sum_taker_long_short_vol_ratio": 0.8,
                }
            ],
            batch_id=21,
        )

        self.assertEqual(datetime(2026, 3, 30, 10, 5, 0), rows[0]["timestamp"])
        self.assertEqual(123.0, rows[0]["open_interest"])
        self.assertEqual(456.0, rows[0]["open_interest_value"])
        self.assertEqual(1.3, rows[0]["top_long_short_ratio"])
        self.assertEqual(0.8, rows[0]["taker_buy_sell_ratio"])
        self.assertEqual(21, rows[0]["ingest_batch_id"])

    def test_metrics_adapter_normalizes_epoch_timestamps_to_utc(self):
        rows = schema_module.MetricsAdapter.to_new_schema(
            [
                {
                    "symbol": "BTCUSDT",
                    "create_time": 1774865100,
                    "sum_open_interest": 123.0,
                }
            ],
            batch_id=21,
        )

        self.assertEqual(datetime.utcfromtimestamp(1774865100), rows[0]["timestamp"])

    def test_metrics_adapter_roundtrip_drops_raw_only_fields(self):
        rows = schema_module.MetricsAdapter.to_legacy_schema(
            [
                {
                    "exchange": "binance",
                    "symbol": "BTCUSDT",
                    "timestamp": datetime(2026, 3, 30, 10, 5, 0),
                    "open_interest": 123.0,
                    "open_interest_value": 456.0,
                    "top_long_short_ratio": 1.3,
                    "taker_buy_sell_ratio": 0.8,
                    "ingest_batch_id": 7,
                    "updated_at": datetime(2026, 3, 30, 10, 6, 0),
                }
            ]
        )

        self.assertEqual(datetime(2026, 3, 30, 10, 5, 0), rows[0]["create_time"])
        self.assertEqual(123.0, rows[0]["sum_open_interest"])
        self.assertEqual(456.0, rows[0]["sum_open_interest_value"])
        self.assertEqual(1.3, rows[0]["count_toptrader_long_short_ratio"])
        self.assertEqual(0.8, rows[0]["sum_taker_long_short_vol_ratio"])
        self.assertNotIn("ingest_batch_id", rows[0])

    def test_kline_adapter_roundtrip_preserves_supported_legacy_fields(self):
        legacy_row = {
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "bucket_ts": datetime(2026, 3, 30, 10, 0, 0),
            "trade_count": 8,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 12.0,
            "quote_volume": 18.0,
            "is_closed": True,
            "source": "collector",
        }

        raw_rows = schema_module.KlineAdapter.to_new_schema([legacy_row], batch_id=11, interval="1m")
        legacy_rows = schema_module.KlineAdapter.to_legacy_schema(raw_rows)

        self.assertEqual(legacy_row["bucket_ts"], legacy_rows[0]["bucket_ts"])
        self.assertEqual(legacy_row["trade_count"], legacy_rows[0]["trade_count"])
        self.assertEqual(legacy_row["open"], legacy_rows[0]["open"])
        self.assertEqual(legacy_row["close"], legacy_rows[0]["close"])
        self.assertEqual(legacy_row["volume"], legacy_rows[0]["volume"])
        self.assertEqual(legacy_row["quote_volume"], legacy_rows[0]["quote_volume"])
        self.assertEqual(legacy_row["is_closed"], legacy_rows[0]["is_closed"])
        self.assertEqual(legacy_row["source"], legacy_rows[0]["source"])

    def test_metrics_adapter_roundtrip_preserves_supported_legacy_fields(self):
        legacy_row = {
            "exchange": "binance_futures_um",
            "symbol": "BTCUSDT",
            "create_time": datetime(2026, 3, 30, 10, 5, 0),
            "sum_open_interest": 123.0,
            "sum_open_interest_value": 456.0,
            "count_toptrader_long_short_ratio": 1.3,
            "count_long_short_ratio": 1.1,
            "sum_taker_long_short_vol_ratio": 0.8,
            "source": "collector",
            "is_closed": True,
        }

        raw_rows = schema_module.MetricsAdapter.to_new_schema([legacy_row], batch_id=21)
        legacy_rows = schema_module.MetricsAdapter.to_legacy_schema(raw_rows)

        self.assertEqual(legacy_row["create_time"], legacy_rows[0]["create_time"])
        self.assertEqual(legacy_row["sum_open_interest"], legacy_rows[0]["sum_open_interest"])
        self.assertEqual(legacy_row["sum_open_interest_value"], legacy_rows[0]["sum_open_interest_value"])
        self.assertEqual(
            legacy_row["count_toptrader_long_short_ratio"],
            legacy_rows[0]["count_toptrader_long_short_ratio"],
        )
        self.assertEqual(legacy_row["count_long_short_ratio"], legacy_rows[0]["count_long_short_ratio"])
        self.assertEqual(legacy_row["sum_taker_long_short_vol_ratio"], legacy_rows[0]["sum_taker_long_short_vol_ratio"])
        self.assertEqual(legacy_row["exchange"], legacy_rows[0]["exchange"])
        self.assertEqual(legacy_row["source"], legacy_rows[0]["source"])

    def test_schema_adapter_rejects_unsafe_schema_identifier(self):
        with self.assertRaises(ValueError):
            schema_module.SchemaAdapter(write_mode="raw", market_db_schema="market_data", raw_db_schema="raw;drop")


if __name__ == "__main__":
    unittest.main()
