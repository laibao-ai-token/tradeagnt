from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(module_name: str, relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class SymbolSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script("tradecat_get_symbol_snapshot", "scripts/tradecat_get_symbol_snapshot.py")
        self.now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    def test_build_payload_success(self) -> None:
        def runner(cmd, args):
            if "tradecat_get_quotes" in str(cmd):
                return {"data": {"price": 100}, "ts": self.now.isoformat()}
            return {"data": [{"rule": "macd"}], "ts": self.now.isoformat()}

        payload = self.module.build_payload("BTCUSDT", "1h", runner=runner, now=self.now)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["symbol"], "BTCUSDT")
        self.assertEqual(payload["warnings"], [])

    def test_build_payload_includes_warnings(self) -> None:
        payload = self.module.build_payload("BTCUSDT", "1h", runner=lambda *args, **kwargs: {"data": None}, now=self.now)
        self.assertIn("quotes unavailable", payload["warnings"])
        self.assertIn("signals unavailable", payload["warnings"])

    def test_build_payload_exposes_source_status_with_error_code(self) -> None:
        payload = self.module.build_payload(
            "BTCUSDT",
            "1h",
            runner=lambda *args, **kwargs: {
                "ok": False,
                "data": None,
                "error": {"code": "upstream_failed", "message": "boom"},
            },
            now=self.now,
        )
        status = payload["data"]["source_status"]
        self.assertFalse(status["quotes"]["ok"])
        self.assertEqual(status["quotes"]["error"]["code"], "upstream_failed")
        self.assertFalse(status["signals"]["ok"])
        self.assertEqual(status["signals"]["error"]["code"], "upstream_failed")


class SignalContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script("tradecat_get_signal_context", "scripts/tradecat_get_signal_context.py")
        self.now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    def test_build_payload_success(self) -> None:
        def runner(cmd, args):
            if "tradecat_get_signals" in str(cmd):
                return {"data": [{"ts": "2026-04-06T11:59:00+00:00"}], "ts": self.now.isoformat()}
            return {"data": {"price": 70000}, "ts": self.now.isoformat()}

        payload = self.module.build_payload("BTCUSDT", "1h", 5, runner=runner, now=self.now)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["limit"], 5)
        self.assertEqual(payload["warnings"], [])

    def test_build_payload_reports_source_status_when_quotes_missing(self) -> None:
        def runner(cmd, args):
            if "tradecat_get_signals" in str(cmd):
                return {"ok": True, "data": [{"ts": "2026-04-06T11:59:00+00:00"}]}
            return {"ok": False, "data": None, "error": {"code": "quote_down", "message": "down"}}

        payload = self.module.build_payload("BTCUSDT", "1h", 5, runner=runner, now=self.now)
        self.assertIn("quotes unavailable", payload["warnings"])
        self.assertEqual(payload["data"]["source_status"]["quotes"]["error"]["code"], "quote_down")
        self.assertTrue(payload["data"]["source_status"]["signals"]["ok"])


class MarketStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script("tradecat_get_market_state", "scripts/tradecat_get_market_state.py")
        self.now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    def test_build_payload_uses_health_payload(self) -> None:
        health_payload = {
            "data": {
                "services": {"signal_service": "running"},
                "databases": {"signal_history": "ok"},
            }
        }
        payload = self.module.build_payload(health_payload, now=self.now)
        self.assertEqual(payload["data"]["services"]["signal_service"], "running")
        self.assertFalse(payload["warnings"])
        self.assertTrue(payload["data"]["source_status"]["service_health"]["ok"])


class BacktestHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script("tradecat_get_backtest_health", "scripts/tradecat_get_backtest_health.py")
        self.now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    def test_build_payload_reads_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "20260406-120000"
            run_dir.mkdir()
            (run_dir / "metrics.json").write_text(
                json.dumps({"net_pnl": 12.3, "total_return_pct": 1.2, "max_drawdown_pct": -3.4}),
                encoding="utf-8",
            )
            payload = self.module.build_payload(artifacts_dir=Path(tmp_dir), now=self.now)
        self.assertEqual(payload["data"]["total_runs"], 1)
        self.assertFalse(payload["warnings"])


class ServiceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script("tradecat_get_service_health", "scripts/tradecat_get_service_health.py")
        self.now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    def test_build_payload_uses_dependency_injection(self) -> None:
        payload = self.module.build_payload(
            service_checker=lambda name: f"{name}-running",
            database_checker=lambda path: "ok",
            indicator_db_override="/tmp/indicator.db",
            now=self.now,
        )
        self.assertEqual(payload["data"]["services"]["signal_service"], "signal-service-running")
        self.assertEqual(payload["data"]["databases"]["indicator"], "ok")


class ContextPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script("tradecat_get_context_pack", "scripts/tradecat_get_context_pack.py")
        self.now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    def test_build_payload_success(self) -> None:
        def runner(cmd, args):
            return {"data": {"value": str(cmd)}, "ts": self.now.isoformat()}

        payload = self.module.build_payload(
            symbol="BTCUSDT",
            timeframe="1h",
            news_limit=3,
            signal_limit=5,
            runner=runner,
            now=self.now,
        )
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["warnings"])
        self.assertIn("freshness", payload["data"])
        self.assertIn("quotes", payload["data"]["freshness"])

    def test_build_payload_warns_on_missing_blocks(self) -> None:
        payload = self.module.build_payload(
            symbol="BTCUSDT",
            timeframe="1h",
            news_limit=3,
            signal_limit=5,
            runner=lambda *args, **kwargs: {"data": None, "ts": None},
            now=self.now,
        )
        self.assertGreaterEqual(len(payload["warnings"]), 4)
        self.assertTrue(payload["data"]["freshness"]["quotes"]["stale"])
        self.assertIn("quotes missing", " ".join(payload["data"]["risk_summary"]))

    def test_build_payload_treats_error_quote_list_as_missing(self) -> None:
        def runner(cmd, args):
            if "tradecat_get_quotes" in str(cmd):
                return {
                    "ok": True,
                    "data": [{"ok": False, "error": {"code": "quote_not_found"}}],
                    "ts": None,
                }
            return {"ok": True, "data": {"value": "ok"}, "ts": self.now.isoformat()}

        payload = self.module.build_payload(
            symbol="BTCUSDT",
            timeframe="1h",
            news_limit=3,
            signal_limit=5,
            runner=runner,
            now=self.now,
        )
        self.assertIn("quotes unavailable", payload["warnings"])
        self.assertIn("quotes missing", payload["data"]["risk_summary"])

    def test_build_payload_propagates_upstream_warnings(self) -> None:
        def runner(cmd, args):
            if "tradecat_get_backtest_health" in str(cmd):
                return {
                    "ok": True,
                    "data": {"total_runs": 0, "latest_runs": []},
                    "ts": self.now.isoformat(),
                    "warnings": ["no backtest runs found"],
                }
            return {"ok": True, "data": {"value": "ok"}, "ts": self.now.isoformat()}

        payload = self.module.build_payload(
            symbol="BTCUSDT",
            timeframe="1h",
            news_limit=3,
            signal_limit=5,
            runner=runner,
            now=self.now,
        )
        self.assertIn("backtest: no backtest runs found", payload["warnings"])
        self.assertIn("backtest: no backtest runs found", payload["data"]["risk_summary"])

    def test_build_payload_uses_backtest_health_command(self) -> None:
        seen_commands = []

        def runner(cmd, args):
            seen_commands.append(Path(cmd).name)
            return {"data": {"ok": True}, "ts": self.now.isoformat()}

        self.module.build_payload(
            symbol="BTCUSDT",
            timeframe="1h",
            news_limit=3,
            signal_limit=5,
            runner=runner,
            now=self.now,
        )
        self.assertIn("tradecat_get_backtest_health.py", seen_commands)
        self.assertNotIn("tradecat_get_backtest_summary.py", seen_commands)


class PaperTradeCliArgTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script("tradecat_paper_trade", "scripts/tradecat_paper_trade.py")

    def test_candidate_positional_args(self) -> None:
        parsed = self.module._parse_candidate_args(["BTCUSDT", "LONG", "0.10"])
        self.assertEqual(parsed["symbol"], "BTCUSDT")
        self.assertEqual(parsed["side"], "LONG")
        self.assertEqual(parsed["size_pct"], 0.10)
        self.assertEqual(parsed["score"], 80)
        self.assertEqual(parsed["reason"], "test")
        self.assertIsNone(parsed["idempotency_key"])
        self.assertFalse(parsed["reuse_finalized"])

    def test_candidate_flag_args(self) -> None:
        parsed = self.module._parse_candidate_args(
            [
                "--symbol",
                "ETHUSDT",
                "--side",
                "SHORT",
                "--size-pct",
                "0.25",
                "--score",
                "95",
                "--reason",
                "manual-check",
                "--idempotency-key",
                "intent:eth:short:001",
                "--reuse-finalized",
            ]
        )
        self.assertEqual(parsed["symbol"], "ETHUSDT")
        self.assertEqual(parsed["side"], "SHORT")
        self.assertEqual(parsed["size_pct"], 0.25)
        self.assertEqual(parsed["score"], 95)
        self.assertEqual(parsed["reason"], "manual-check")
        self.assertEqual(parsed["idempotency_key"], "intent:eth:short:001")
        self.assertTrue(parsed["reuse_finalized"])

    def test_candidate_positional_with_overrides(self) -> None:
        parsed = self.module._parse_candidate_args(
            [
                "BTCUSDT",
                "LONG",
                "0.10",
                "--score",
                "88",
                "--reason",
                "override",
                "--idempotency-key",
                "intent:btc:long:001",
            ]
        )
        self.assertEqual(parsed["score"], 88)
        self.assertEqual(parsed["reason"], "override")
        self.assertEqual(parsed["idempotency_key"], "intent:btc:long:001")

    def test_candidate_missing_required_args(self) -> None:
        with self.assertRaises(ValueError):
            self.module._parse_candidate_args(["--symbol", "BTCUSDT", "--side", "LONG"])


if __name__ == "__main__":
    unittest.main()
