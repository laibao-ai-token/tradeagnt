from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "tradecat_execution_audit.py"


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


class ExecutionAuditCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.audit_dir = Path(self.temp_dir.name) / "audit"
        self.env = os.environ.copy()
        self.env["TRADECAT_EXECUTION_AUDIT_DIR"] = str(self.audit_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_start_sync_replay_and_list_use_overridden_log_dir(self) -> None:
        started = _run_cli("start", "intent-1", "order-1", "BTCUSDT", "LONG", "0.1", env=self.env)
        self.assertTrue(started["ok"])
        self.assertIn("request", started)
        trace_id = started["data"]["trace_id"]

        for args in (
            ("validate", trace_id, "true"),
            ("stage", trace_id),
            ("confirm", trace_id),
            ("execute", trace_id, "50000"),
            ("sync", trace_id),
        ):
            payload = _run_cli(*args, env=self.env)
            self.assertTrue(payload["ok"])

        replay = _run_cli("replay", trace_id, env=self.env)
        self.assertTrue(replay["ok"])
        self.assertEqual(replay["data"]["replay"]["status"], "COMPLETED")

        listed = _run_cli("list", env=self.env)
        self.assertTrue(listed["ok"])
        self.assertIn(trace_id, listed["data"]["traces"])
        self.assertTrue((self.audit_dir / f"{trace_id}.jsonl").exists())

    def test_replay_missing_trace_returns_structured_error(self) -> None:
        payload = _run_cli("replay", "trace_missing", env=self.env)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["data"]["error_code"], "trace_not_found")
        self.assertEqual(payload["error"], "trace not found: trace_missing")

    def test_execute_invalid_fill_price_returns_structured_error(self) -> None:
        payload = _run_cli("execute", "trace_x", "not_a_number", env=self.env)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["data"]["error_code"], "invalid_argument")
        self.assertEqual(payload["error"], "invalid fill_price: not_a_number")


if __name__ == "__main__":
    unittest.main()
