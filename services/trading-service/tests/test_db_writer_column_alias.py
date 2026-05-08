import logging
import sqlite3
import sys
import types

import pandas as pd

if "psycopg_pool" not in sys.modules:
    class _DummyConnectionPool(object):
        def __init__(self, *args, **kwargs):
            del args
            del kwargs

    sys.modules["psycopg_pool"] = types.SimpleNamespace(ConnectionPool=_DummyConnectionPool)

from src.db.reader import DataWriter


def test_datawriter_maps_english_key_columns_to_cn(tmp_path):
    sqlite_path = tmp_path / "indicators.db"
    writer = DataWriter(sqlite_path=sqlite_path)
    conn = None
    try:
        df = pd.DataFrame(
            [
                {
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "bucket_ts": "2026-04-06 10:00:00",
                    "信号分数": 88.5,
                }
            ]
        )
        writer.write("test_indicator_table", df)

        conn = sqlite3.connect(str(sqlite_path))
        cols = [row[1] for row in conn.execute("PRAGMA table_info([test_indicator_table])").fetchall()]
        assert "交易对" in cols
        assert "周期" in cols
        assert "数据时间" in cols
        row = conn.execute(
            "SELECT [交易对], [周期], [数据时间], [信号分数] FROM [test_indicator_table] LIMIT 1"
        ).fetchone()
        assert row[0] == "BTCUSDT"
        assert row[1] == "5m"
        assert row[2] == "2026-04-06 10:00:00"
        assert float(row[3]) == 88.5
    finally:
        if conn is not None:
            conn.close()
        writer.close()


def test_datawriter_logs_warning_when_key_columns_missing(tmp_path, caplog):
    sqlite_path = tmp_path / "indicators.db"
    writer = DataWriter(sqlite_path=sqlite_path)
    try:
        df = pd.DataFrame([{"value": 1.23}])
        with caplog.at_level(logging.WARNING, logger="indicator_service.db"):
            writer.write("test_missing_keys", df)

        assert any("key columns missing" in record.message for record in caplog.records)
    finally:
        writer.close()
