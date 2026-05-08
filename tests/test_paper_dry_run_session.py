from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.test_domain_read_models import _load_script


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "tradecat_paper_dry_run_session.py"


class PaperDryRunSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script("tradecat_paper_dry_run_session", "scripts/tradecat_paper_dry_run_session.py")
        self.now = datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc)

    def test_build_payload_runs_fixed_ticks_and_summarizes_results(self) -> None:
        sleep_calls: list[float] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = self.module.build_payload(
                symbol="BTCUSDT",
                side="LONG",
                size_pct=0.10,
                price=80000.0,
                duration_seconds=3600,
                interval_seconds=60,
                max_ticks=3,
                now=self.now,
                sleep_fn=lambda seconds: sleep_calls.append(seconds),
                artifacts_dir=Path(tmp_dir) / "paper",
                execution_audit_dir=Path(tmp_dir) / "audit",
            )

        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual(data["summary"]["ticks_completed"], 3)
        self.assertEqual(data["summary"]["guard_passed_ticks"], 3)
        self.assertEqual(data["summary"]["guard_failed_ticks"], 0)
        self.assertEqual(len(data["results"]), 3)
        self.assertEqual(sleep_calls, [60.0, 60.0])

    def test_build_payload_dry_run_does_not_mutate_portfolio_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = self.module.build_payload(
                symbol="BTCUSDT",
                side="LONG",
                size_pct=0.10,
                price=80000.0,
                duration_seconds=3600,
                interval_seconds=60,
                max_ticks=2,
                now=self.now,
                sleep_fn=lambda seconds: None,
                artifacts_dir=Path(tmp_dir) / "paper",
                execution_audit_dir=Path(tmp_dir) / "audit",
            )

        self.assertTrue(payload["ok"])
        before_stats = payload["data"]["stats_before"]
        after_stats = payload["data"]["stats_after"]
        report_after = payload["data"]["report_after"]
        self.assertEqual(before_stats["total_trades"], 0)
        self.assertEqual(after_stats["total_trades"], 0)
        self.assertEqual(after_stats["open_positions"], 0)
        self.assertEqual(report_after["records"], 0)
        self.assertEqual(report_after["filled"], 0)

    def test_cli_returns_structured_error_for_invalid_interval(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--symbol",
                "BTCUSDT",
                "--side",
                "LONG",
                "--size-pct",
                "0.10",
                "--price",
                "80000",
                "--duration-seconds",
                "3600",
                "--interval-seconds",
                "0",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertTrue(completed.stdout.strip())
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_argument")


if __name__ == "__main__":
    unittest.main()
