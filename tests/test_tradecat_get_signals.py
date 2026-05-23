"""Tests for scripts/tradecat_get_signals.py."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "tradecat_get_signals.py"


def _seed_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                strength INTEGER DEFAULT 0,
                message TEXT,
                timeframe TEXT,
                price REAL,
                source TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO signal_history
            (timestamp, symbol, signal_type, direction, strength, message, timeframe, price, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-05-22T10:00:00", "BTC_USDT", "rsi_oversold", "LONG", 80, "test", "5m", 65000.0, "tui_poller"),
        )
        conn.commit()


class TradecatGetSignalsTests(unittest.TestCase):
    def test_cli_reads_seeded_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "signal_history.db"
            _seed_db(db)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--db-path", str(db), "--symbol", "BTCUSDT", "--limit", "3"],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["data"]), 1)
            self.assertEqual(payload["data"][0]["symbol"], "BTC_USDT")

    def test_missing_db_returns_source_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.db"
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--db-path", str(missing)],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error"]["code"], "source_unavailable")


if __name__ == "__main__":
    unittest.main()
