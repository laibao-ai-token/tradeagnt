from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "tradecat_paper_trade.py"


def _run_cli(*args: str, env: dict[str, str]) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    if not completed.stdout.strip():
        raise AssertionError(f"empty stdout for args={args}, stderr={completed.stderr!r}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise AssertionError(f"non-dict payload for args={args}: {payload!r}")
    return payload


class PaperTradeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.paper_dir = root / "paper"
        self.audit_dir = root / "audit"
        self.env = os.environ.copy()
        self.env["TRADECAT_PAPER_ARTIFACTS_DIR"] = str(self.paper_dir)
        self.env["TRADECAT_EXECUTION_AUDIT_DIR"] = str(self.audit_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_candidate_execute_report_roundtrip(self) -> None:
        candidate = _run_cli("candidate", "BTCUSDT", "LONG", "0.05", env=self.env)
        self.assertTrue(candidate["ok"])
        self.assertIn("request", candidate)
        order = candidate["data"]["order"]
        order_id = order["order_id"]
        self.assertEqual(order["score"], 80)
        self.assertEqual(order["reason"], "test")

        signal_ts = datetime.now(timezone.utc).isoformat()
        executed = _run_cli("execute", order_id, "80000", "--signal-ts", signal_ts, env=self.env)
        self.assertTrue(executed["ok"])
        self.assertTrue(executed["data"]["success"])
        self.assertEqual(executed["data"]["order_id"], order_id)
        self.assertEqual(executed["request"]["signal_ts"], signal_ts)

        report = _run_cli("report", "20", env=self.env)
        self.assertTrue(report["ok"])
        summary = report["data"]["report"]
        self.assertEqual(summary["filled"], 1)
        self.assertEqual(summary["records"], 1)
        self.assertEqual(summary["latest"]["order_id"], order_id)

    def test_candidate_flag_args_roundtrip(self) -> None:
        payload = _run_cli(
            "candidate",
            "--symbol",
            "ETHUSDT",
            "--side",
            "SHORT",
            "--size-pct",
            "0.15",
            "--score",
            "91",
            "--reason",
            "cli-check",
            "--idempotency-key",
            "intent:eth:short:cli",
            env=self.env,
        )
        self.assertTrue(payload["ok"])
        order = payload["data"]["order"]
        self.assertEqual(order["symbol"], "ETHUSDT")
        self.assertEqual(order["side"], "SHORT")
        self.assertEqual(order["qty"], 0.15)
        self.assertEqual(order["score"], 91)
        self.assertEqual(order["reason"], "cli-check")
        self.assertEqual(order["idempotency_key"], "intent:eth:short:cli")

    def test_execute_without_signal_ts_is_blocked_by_freshness_guard(self) -> None:
        candidate = _run_cli("candidate", "BTCUSDT", "LONG", "0.05", env=self.env)
        order_id = candidate["data"]["order"]["order_id"]

        executed = _run_cli("execute", order_id, "80000", env=self.env)

        self.assertFalse(executed["ok"])
        self.assertEqual(executed["data"]["error_code"], "guard_validation_failed")
        self.assertIn("data_freshness", executed["data"]["guard"]["failed_rules"])

    def test_candidate_invalid_args_returns_structured_error(self) -> None:
        payload = _run_cli("candidate", "--symbol", "BTCUSDT", "--side", "LONG", env=self.env)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["data"]["error_code"], "invalid_candidate_args")
        self.assertIn("size_pct", payload["data"]["error"])

    def test_execute_invalid_price_returns_structured_error(self) -> None:
        payload = _run_cli("execute", "order_x", "not_a_number", env=self.env)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["data"]["error_code"], "invalid_argument")
        self.assertIn("price", payload["data"]["error"])

    def test_compare_backtest_and_paper_metrics(self) -> None:
        root = Path(self.temp_dir.name) / "artifacts" / "backtest"
        run_dir = root / "20260411-120000"
        run_dir.mkdir(parents=True)
        (run_dir / "metrics.json").write_text(
            json.dumps(
                {
                    "run_id": "unit-run",
                    "mode": "history_signal",
                    "start": "2026-04-01 00:00:00+00:00",
                    "end": "2026-04-07 00:00:00+00:00",
                    "symbols": ["BTCUSDT"],
                    "timeframe": "1m",
                    "total_return_pct": 12.5,
                    "max_drawdown_pct": 4.2,
                    "trade_count": 14,
                    "win_rate_pct": 57.1,
                    "profit_factor": 1.4,
                    "strategy_label": "unit",
                }
            ),
            encoding="utf-8",
        )

        candidate = _run_cli("candidate", "BTCUSDT", "LONG", "0.05", env=self.env)
        order_id = candidate["data"]["order"]["order_id"]
        signal_ts = datetime.now(timezone.utc).isoformat()
        executed = _run_cli("execute", order_id, "80000", "--signal-ts", signal_ts, env=self.env)
        self.assertTrue(executed["ok"])

        compare = _run_cli(
            "compare",
            "--backtest-run-id",
            "unit-run",
            "--artifacts-root",
            str(root),
            env=self.env,
        )
        self.assertTrue(compare["ok"])
        payload = compare["data"]["compare"]
        self.assertEqual(payload["backtest"]["run_id"], "unit-run")
        self.assertEqual(payload["backtest"]["trade_count"], 14)
        self.assertEqual(payload["paper"]["trade_count"], 1)
        self.assertEqual(payload["delta"]["trade_count"], -13)
        self.assertIn("notes", payload)

    def test_portfolio_reports_total_equity_not_just_cash_balance(self) -> None:
        candidate = _run_cli("candidate", "BTCUSDT", "LONG", "0.05", env=self.env)
        order_id = candidate["data"]["order"]["order_id"]
        signal_ts = datetime.now(timezone.utc).isoformat()
        executed = _run_cli("execute", order_id, "80000", "--signal-ts", signal_ts, env=self.env)
        self.assertTrue(executed["ok"])

        stats = _run_cli("stats", env=self.env)
        stats_payload = stats["data"]["stats"]
        self.assertIn("cash_balance", stats_payload)
        self.assertIn("position_market_value", stats_payload)
        self.assertIn("total_equity", stats_payload)
        self.assertAlmostEqual(stats_payload["cash_balance"], 5997.6, places=6)
        self.assertAlmostEqual(stats_payload["position_market_value"], 4000.8, places=6)
        self.assertAlmostEqual(stats_payload["total_equity"], 9998.4, places=6)
        self.assertGreater(stats_payload["return_pct"], -1.0)

        portfolio = _run_cli("portfolio", env=self.env)
        self.assertTrue(portfolio["ok"])
        portfolio_payload = portfolio["data"]["portfolio"]
        self.assertAlmostEqual(portfolio_payload["total_equity"], 9998.4, places=6)
        self.assertEqual(portfolio_payload["open_positions"], 1)


if __name__ == "__main__":
    unittest.main()
