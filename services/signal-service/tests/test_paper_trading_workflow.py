"""Workflow tests for paper trading orchestrator integration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from src.paper_trading import PaperTradingOrchestrator
from src.paper_trading.models import OrderStatus
from src.risk import GuardConfig


def _create_signal_history_db(db_path, *, direction: str = "BUY", strength: int = 85) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                strength INTEGER NOT NULL,
                message TEXT,
                timeframe TEXT,
                price REAL,
                source TEXT DEFAULT 'sqlite',
                extra TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO signal_history
            (timestamp, symbol, signal_type, direction, strength, message, timeframe, price, source, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                "BTCUSDT",
                "macd",
                direction,
                strength,
                "signal",
                "1m",
                70000.0,
                "sqlite",
                "{}",
            ),
        )


def test_paper_workflow_execute_success(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    orchestrator = PaperTradingOrchestrator(
        initial_equity=10000.0,
        guard_config=GuardConfig(
            max_position_pct=0.5,
            max_single_symbol_pct=0.5,
            cooldown_seconds=60,
            max_drawdown_pct=0.5,
            max_signal_age_seconds=600,
        ),
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )

    order = orchestrator.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=90,
        reason="unit-test",
    )
    result = orchestrator.confirm_and_execute(
        order.order_id,
        execution_price=80000.0,
        last_signal_ts=now - timedelta(seconds=30),
    )

    assert result["success"] is True
    assert result["trace_id"]
    assert result["audit"]["status"] == "COMPLETED"
    assert orchestrator.ledger.orders[order.order_id].status == OrderStatus.FILLED
    assert len(orchestrator.ledger.fills) == 1
    stats = orchestrator.get_stats()
    assert stats["cash_balance"] < stats["initial_equity"]
    assert stats["position_market_value"] > 0
    assert stats["total_equity"] > 0
    assert stats["return_pct"] > -1.0


def test_paper_workflow_rejects_when_guard_fails(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    orchestrator = PaperTradingOrchestrator(
        initial_equity=10000.0,
        guard_config=GuardConfig(
            whitelist=["ETHUSDT"],
            max_signal_age_seconds=600,
        ),
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )

    order = orchestrator.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=85,
        reason="whitelist-fail",
    )
    result = orchestrator.confirm_and_execute(
        order.order_id,
        execution_price=70000.0,
        last_signal_ts=now - timedelta(seconds=10),
    )

    assert result["success"] is False
    assert result["error"] == "guard validation failed"
    assert "whitelist" in result["guard"]["failed_rules"]
    assert orchestrator.ledger.orders[order.order_id].status == OrderStatus.REJECTED
    assert result["audit"]["status"] == "REJECTED"


def test_generate_candidate_from_latest_signal(tmp_path) -> None:
    db_path = tmp_path / "signal_history.db"
    _create_signal_history_db(db_path, direction="BUY", strength=88)
    orchestrator = PaperTradingOrchestrator(
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )

    generated = orchestrator.generate_candidate_from_latest_signal(
        symbol="BTCUSDT",
        timeframe="1m",
        size_pct=0.12,
        min_strength=70,
        db_path=db_path,
    )

    assert generated["ok"] is True
    assert generated["order"].side.value == "LONG"
    assert generated["order"].qty == 0.12
    assert generated["signal"]["strength"] == 88


def test_generate_candidate_from_signal_respects_strength_threshold(tmp_path) -> None:
    db_path = tmp_path / "signal_history.db"
    _create_signal_history_db(db_path, direction="BUY", strength=40)
    orchestrator = PaperTradingOrchestrator(
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )

    generated = orchestrator.generate_candidate_from_latest_signal(
        symbol="BTCUSDT",
        timeframe="1m",
        size_pct=0.1,
        min_strength=70,
        db_path=db_path,
    )

    assert generated["ok"] is False
    assert generated["error_code"] == "signal_strength_too_low"


def test_execute_with_retry_returns_attempt_metadata(tmp_path) -> None:
    orchestrator = PaperTradingOrchestrator(
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )

    result = orchestrator.confirm_and_execute_with_retry("order_missing", execution_price=100.0, max_retries=3)
    assert result["success"] is False
    assert result["error_code"] == "order_not_found"
    assert result["attempt"] == 1
    assert result["max_attempts"] == 4


def test_validate_requires_signal_timestamp(tmp_path) -> None:
    orchestrator = PaperTradingOrchestrator(
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )

    result = orchestrator.validate("BTCUSDT", "LONG", 0.1, last_signal_ts=None)

    assert result["passed"] is False
    assert "data_freshness" in result["failed_rules"]
    assert result["subchecks"]["data_freshness"]["passed"] is False


def test_candidate_persists_across_orchestrator_instances(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    artifacts_dir = tmp_path / "paper"
    execution_dir = tmp_path / "audit"
    config = GuardConfig(max_signal_age_seconds=600)

    orchestrator_a = PaperTradingOrchestrator(
        guard_config=config,
        artifacts_dir=artifacts_dir,
        execution_log_dir=execution_dir,
    )
    order = orchestrator_a.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=80,
        reason="persist-check",
    )

    orchestrator_b = PaperTradingOrchestrator(
        guard_config=config,
        artifacts_dir=artifacts_dir,
        execution_log_dir=execution_dir,
    )
    assert order.order_id in orchestrator_b.ledger.orders

    result = orchestrator_b.confirm_and_execute(
        order.order_id,
        execution_price=80000.0,
        last_signal_ts=now - timedelta(seconds=20),
    )
    assert result["success"] is True
    assert orchestrator_b.ledger.orders[order.order_id].status == OrderStatus.FILLED
    stats = orchestrator_b.get_stats()
    assert stats["total_trades"] == 1
    assert stats["open_positions"] == 1
    assert stats["position_market_value"] > 0


def test_generate_candidate_is_idempotent_for_same_key(tmp_path) -> None:
    orchestrator = PaperTradingOrchestrator(
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )

    first = orchestrator.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=80,
        reason="idempotency",
        idempotency_key="intent:btc:long:001",
    )
    second = orchestrator.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=80,
        reason="idempotency",
        idempotency_key="intent:btc:long:001",
    )

    assert first.order_id == second.order_id
    assert len(orchestrator.ledger.orders) == 1


def test_generate_candidate_creates_new_order_after_finalized(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    orchestrator = PaperTradingOrchestrator(
        guard_config=GuardConfig(max_signal_age_seconds=600),
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )
    first = orchestrator.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=80,
        reason="idempotency-finalized",
        idempotency_key="intent:btc:long:finalized",
    )
    executed = orchestrator.confirm_and_execute(
        first.order_id,
        execution_price=80000.0,
        last_signal_ts=now - timedelta(seconds=10),
    )
    assert executed["success"] is True

    second = orchestrator.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=80,
        reason="idempotency-finalized",
        idempotency_key="intent:btc:long:finalized",
    )
    assert second.order_id != first.order_id


def test_from_signal_reuses_order_even_after_finalized(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    db_path = tmp_path / "signal_history.db"
    _create_signal_history_db(db_path, direction="BUY", strength=88)
    orchestrator = PaperTradingOrchestrator(
        guard_config=GuardConfig(max_signal_age_seconds=600),
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )

    first = orchestrator.generate_candidate_from_latest_signal(
        symbol="BTCUSDT",
        timeframe="1m",
        size_pct=0.12,
        min_strength=70,
        db_path=db_path,
    )
    assert first["ok"] is True
    order = first["order"]
    executed = orchestrator.confirm_and_execute(
        order.order_id,
        execution_price=80000.0,
        last_signal_ts=now - timedelta(seconds=10),
    )
    assert executed["success"] is True

    second = orchestrator.generate_candidate_from_latest_signal(
        symbol="BTCUSDT",
        timeframe="1m",
        size_pct=0.12,
        min_strength=70,
        db_path=db_path,
    )
    assert second["ok"] is True
    assert second["order"].order_id == order.order_id


def test_execute_success_emits_attribution_report_summary(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    orchestrator = PaperTradingOrchestrator(
        initial_equity=10000.0,
        guard_config=GuardConfig(max_signal_age_seconds=600),
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )
    order = orchestrator.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=90,
        reason="summary-check",
    )

    result = orchestrator.confirm_and_execute(
        order.order_id,
        execution_price=80000.0,
        last_signal_ts=now - timedelta(seconds=10),
    )

    assert result["success"] is True
    assert result["attribution"]["outcome"] == "FILLED"
    assert result["attribution"]["symbol"] == "BTCUSDT"
    assert result["attribution"]["fee"] > 0
    summary = orchestrator.get_execution_report_summary(limit=20)
    assert summary["records"] == 1
    assert summary["filled"] == 1
    assert summary["rejected"] == 0
    assert summary["symbols"]["BTCUSDT"]["filled"] == 1
    assert summary["total_fee"] > 0


def test_guard_rejection_emits_rejected_attribution_record(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    orchestrator = PaperTradingOrchestrator(
        initial_equity=10000.0,
        guard_config=GuardConfig(whitelist=["ETHUSDT"], max_signal_age_seconds=600),
        artifacts_dir=tmp_path / "paper",
        execution_log_dir=tmp_path / "audit",
    )
    order = orchestrator.generate_candidate(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        score=80,
        reason="rejection-summary",
    )

    result = orchestrator.confirm_and_execute(
        order.order_id,
        execution_price=70000.0,
        last_signal_ts=now - timedelta(seconds=10),
    )

    assert result["success"] is False
    assert result["attribution"]["outcome"] == "REJECTED"
    assert result["attribution"]["error_code"] == "guard_validation_failed"
    summary = orchestrator.get_execution_report_summary(limit=20)
    assert summary["records"] == 1
    assert summary["filled"] == 0
    assert summary["rejected"] == 1
    assert summary["symbols"]["BTCUSDT"]["rejected"] == 1
