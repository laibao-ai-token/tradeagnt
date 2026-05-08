from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile


SERVICE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from paper_trading.models import OrderStatus
from paper_trading.orchestrator import PaperTradingOrchestrator
from risk import GuardConfig


def test_paper_workflow_success_path_writes_audit_trace() -> None:
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as tmp_dir:
        artifacts_dir = Path(tmp_dir) / "paper"
        audit_dir = Path(tmp_dir) / "audit"
        orchestrator = PaperTradingOrchestrator(
            initial_equity=10000,
            guard_config=GuardConfig(
                max_position_pct=0.8,
                max_single_symbol_pct=0.4,
                cooldown_seconds=60,
                max_signal_age_seconds=600,
            ),
            artifacts_dir=artifacts_dir,
            execution_log_dir=audit_dir,
        )

        order = orchestrator.generate_candidate("BTCUSDT", "LONG", 0.1, 85, "test")
        result = orchestrator.confirm_and_execute(
            order.order_id,
            execution_price=50000,
            last_signal_ts=now - timedelta(seconds=10),
        )

        assert result["success"] is True
        assert result["trace_id"]
        assert orchestrator.ledger.orders[order.order_id].status == OrderStatus.FILLED
        assert len(orchestrator.ledger.fills) == 1
        stats = orchestrator.get_stats()
        assert stats["cash_balance"] < stats["initial_equity"]
        assert stats["position_market_value"] > 0
        assert stats["total_equity"] > 0
        assert stats["return_pct"] > -1.0
        replay = result["audit"]
        phases = [event["phase"] for event in replay["events"]]
        assert phases == ["propose", "validate", "stage", "confirm", "execute", "sync"]
        assert replay["status"] == "COMPLETED"


def test_paper_workflow_rejects_when_guard_fails() -> None:
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as tmp_dir:
        orchestrator = PaperTradingOrchestrator(
            initial_equity=10000,
            guard_config=GuardConfig(max_signal_age_seconds=60),
            artifacts_dir=Path(tmp_dir) / "paper",
            execution_log_dir=Path(tmp_dir) / "audit",
        )
        order = orchestrator.generate_candidate("BTCUSDT", "LONG", 0.1, 85, "stale-signal")

        result = orchestrator.confirm_and_execute(
            order.order_id,
            execution_price=50000,
            last_signal_ts=now - timedelta(minutes=20),
        )

        assert result["success"] is False
        assert result["guard"]["passed"] is False
        assert "data_freshness" in result["guard"]["failed_rules"]
        assert orchestrator.ledger.orders[order.order_id].status == OrderStatus.REJECTED
        replay = result["audit"]
        assert replay["status"] == "REJECTED"
        assert replay["current_phase"] == "validate"


def test_paper_workflow_dry_run_does_not_create_fill() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        orchestrator = PaperTradingOrchestrator(
            initial_equity=10000,
            guard_config=GuardConfig(max_signal_age_seconds=600),
            artifacts_dir=Path(tmp_dir) / "paper",
            execution_log_dir=Path(tmp_dir) / "audit",
        )
        result = orchestrator.dry_run("ETHUSDT", "SHORT", 0.05, execution_price=2500)
        assert result["mode"] == "dry_run"
        assert "guard" in result
        assert result["guard"]["passed"] is False
        assert "data_freshness" in result["guard"]["failed_rules"]
        assert len(orchestrator.ledger.fills) == 0
