import os
import shutil
import tempfile
import unittest
import zipfile
import calendar
from datetime import date, datetime
from decimal import Decimal

from src.adapters import timescale as timescale_module
from tests.storage_fakes import FakeCursor, FakePool

from src.collectors.crypto import backfill as backfill_module


class _FakeTimescale(object):
    def __init__(self):
        self.saved_candles = []
        self.saved_metrics = []
        self.last_interval = None

    def upsert_candles(self, interval, rows):
        self.last_interval = interval
        self.saved_candles.extend([dict(row) for row in rows])
        return len(rows)

    def upsert_metrics(self, rows):
        self.saved_metrics.extend([dict(row) for row in rows])
        return len(rows)

    def close(self):
        return None


def _build_config():
    return type(
        "Config",
        (),
        {
            "runtime": type(
                "Runtime",
                (),
                {
                    "http_proxy": "",
                    "backfill_mode": "days",
                    "backfill_days": 30,
                    "backfill_start_date": "",
                },
            )(),
            "crypto_kline": type(
                "CryptoKline",
                (),
                {
                    "db_exchange": "binance_futures_um",
                    "ccxt_exchange": "binance",
                },
            )(),
            "crypto_metrics": type(
                "CryptoMetrics",
                (),
                {
                    "enabled": True,
                    "interval": "5m",
                },
            )(),
        },
    )()


def _write_zip_csv(zip_path, csv_name, rows):
    archive = zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED)
    try:
        content = []
        for row in rows:
            content.append(",".join(row))
        archive.writestr(csv_name, "\n".join(content) + "\n")
    finally:
        archive.close()


class BackfillTests(unittest.TestCase):
    def setUp(self):
        if hasattr(timescale_module, "reset_shared_pool"):
            timescale_module.reset_shared_pool()
        FakePool.reset()
        self.original_fetch_ohlcv = getattr(backfill_module, "fetch_ohlcv", None)
        self.original_to_candle_rows = getattr(backfill_module, "to_candle_rows", None)

    def tearDown(self):
        if self.original_fetch_ohlcv is not None:
            backfill_module.fetch_ohlcv = self.original_fetch_ohlcv
        if self.original_to_candle_rows is not None:
            backfill_module.to_candle_rows = self.original_to_candle_rows

    def _adapter(self, write_mode):
        return timescale_module.TimescaleAdapter(
            db_url="postgresql://default/db",
            default_db_url="postgresql://default/db",
            market_db_schema="market_data",
            raw_db_schema="raw",
            quality_db_schema="quality",
            write_mode=write_mode,
            pool_factory=FakePool,
        )

    def test_gap_scanner_legacy_uses_legacy_table_and_detects_missing_day(self):
        FakePool.next_cursor = FakeCursor(fetchall_result=[("BTCUSDT", date(2026, 3, 1), 1440)])
        scanner = backfill_module.GapScanner(self._adapter("legacy"), config=_build_config())

        gaps = scanner.scan_klines(["BTCUSDT"], date(2026, 3, 1), date(2026, 3, 2), interval="1m", threshold=0.95)

        cursor = FakePool.created[0].connection_obj.cursor_obj
        self.assertIn('"market_data"."candles_1m"', cursor.execute_calls[0][0])
        self.assertIn("bucket_ts", cursor.execute_calls[0][0])
        self.assertEqual("binance_futures_um", cursor.execute_calls[0][1][0])
        self.assertEqual(1, len(gaps["BTCUSDT"]))
        self.assertEqual(date(2026, 3, 2), gaps["BTCUSDT"][0].date)

    def test_gap_scanner_raw_uses_raw_metrics_table_and_time_field(self):
        FakePool.next_cursor = FakeCursor(fetchall_result=[("BTCUSDT", date(2026, 3, 1), 288)])
        scanner = backfill_module.GapScanner(self._adapter("raw"), config=_build_config())

        gaps = scanner.scan_metrics(["BTCUSDT"], date(2026, 3, 1), date(2026, 3, 1), threshold=0.95)

        cursor = FakePool.created[0].connection_obj.cursor_obj
        self.assertIn('"raw"."crypto_metrics_5m"', cursor.execute_calls[0][0])
        self.assertIn("timestamp", cursor.execute_calls[0][0])
        self.assertEqual("binance_futures_um", cursor.execute_calls[0][1][0])
        self.assertEqual({}, gaps)

    def test_compute_lookback_handles_none_and_start_date(self):
        self.assertEqual(0, backfill_module.compute_lookback("none", 30))
        self.assertEqual(
            30,
            backfill_module.compute_lookback(
                "all",
                30,
                start_date=date(2026, 3, 1),
                today=date(2026, 3, 31),
            ),
        )
        self.assertEqual(7, backfill_module.compute_lookback("days", 7))

    def test_rest_backfiller_fill_kline_gap_collects_and_persists(self):
        fake_ts = _FakeTimescale()
        collector_config = _build_config()
        calls = []

        def _fake_fetch(exchange, symbol, interval="1m", since_ms=None, limit=1000, http_proxy=""):
            del limit
            del http_proxy
            calls.append((exchange, symbol, interval, since_ms))
            if len(calls) == 1:
                first_ts = int(calendar.timegm(datetime(2026, 3, 2, 0, 0).timetuple()) * 1000)
                return [
                    [first_ts, 1, 2, 0.5, 1.5, 100],
                    [first_ts + 60000, 2, 3, 1.2, 2.8, 110],
                ]
            return []

        backfill_module.fetch_ohlcv = _fake_fetch
        backfill_module.to_candle_rows = lambda exchange, symbol, candles, source="ccxt_gap": [
            {
                "exchange": exchange,
                "symbol": symbol,
                "bucket_ts": datetime.utcfromtimestamp(item[0] / 1000),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "source": source,
            }
            for item in candles
        ]

        filler = backfill_module.RestBackfiller(fake_ts, config=collector_config, workers=1)
        gap = backfill_module.GapInfo("BTCUSDT", date(2026, 3, 2), 1440, 1000)

        inserted = filler.fill_kline_gap("BTCUSDT", gap, interval="1m")

        self.assertEqual(2, inserted)
        self.assertEqual("1m", fake_ts.last_interval)
        self.assertEqual(2, len(fake_ts.saved_candles))
        self.assertEqual("BTCUSDT", fake_ts.saved_candles[0]["symbol"])

    def test_zip_backfiller_import_kline_zip_parses_and_persists(self):
        fake_ts = _FakeTimescale()
        temp_dir = tempfile.mkdtemp(prefix="collector-backfill-kline-")
        try:
            filler = backfill_module.ZipBackfiller(fake_ts, config=_build_config(), workers=1, data_dir=temp_dir)
            zip_path = os.path.join(temp_dir, "BTCUSDT-1m.zip")
            ts1 = int(calendar.timegm(datetime(2026, 3, 3, 1, 2).timetuple()) * 1000)
            ts2 = int(calendar.timegm(datetime(2026, 3, 4, 1, 2).timetuple()) * 1000)
            _write_zip_csv(
                zip_path,
                "BTCUSDT-1m.csv",
                [
                    [str(ts1), "1", "2", "0.5", "1.5", "100", "0", "200", "300", "50", "80"],
                    [str(ts2), "2", "3", "1.2", "2.8", "110", "0", "210", "310", "55", "85"],
                ],
            )

            inserted = filler._import_kline_zip(zip_path, "btcusdt", "1m", filter_date=date(2026, 3, 3))

            self.assertEqual(1, inserted)
            self.assertEqual(1, len(fake_ts.saved_candles))
            self.assertEqual("BTCUSDT", fake_ts.saved_candles[0]["symbol"])
            self.assertEqual(300, fake_ts.saved_candles[0]["trade_count"])
        finally:
            shutil.rmtree(temp_dir)

    def test_zip_backfiller_import_metrics_zip_aligns_time_and_persists(self):
        fake_ts = _FakeTimescale()
        temp_dir = tempfile.mkdtemp(prefix="collector-backfill-metrics-")
        try:
            filler = backfill_module.ZipBackfiller(fake_ts, config=_build_config(), workers=1, data_dir=temp_dir)
            zip_path = os.path.join(temp_dir, "BTCUSDT-metrics.zip")
            _write_zip_csv(
                zip_path,
                "BTCUSDT-metrics.csv",
                [
                    ["2026-03-03T00:07:59Z", "BTCUSDT", "10.1", "20.2", "1.1", "1.2", "1.3", "1.4"],
                    ["bad-ts", "BTCUSDT", "oops", "oops"],
                ],
            )

            inserted = filler._import_metrics_zip(zip_path, "btcusdt")

            self.assertEqual(1, inserted)
            self.assertEqual(1, len(fake_ts.saved_metrics))
            self.assertEqual(datetime(2026, 3, 3, 0, 5), fake_ts.saved_metrics[0]["create_time"])
            self.assertEqual(Decimal("10.1"), fake_ts.saved_metrics[0]["sum_open_interest"])
            self.assertEqual(Decimal("1.4"), fake_ts.saved_metrics[0]["sum_taker_long_short_vol_ratio"])
        finally:
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()
