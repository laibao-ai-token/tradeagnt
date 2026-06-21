"""E4 feedback-pack tests."""
from __future__ import annotations

from pathlib import Path


def test_feedback_pack_readonly_policy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PAPER_REPO_TYPE", "memory")
    monkeypatch.setenv("TRADEAGNT_AUDIT_PATH", str(tmp_path / "agent_audit.jsonl"))
    monkeypatch.setenv("SIGNAL_DB_PATH", str(tmp_path / "missing_signal_history.db"))

    from tradecat.agent.audit import append_audit
    from tradecat.agent.feedback import build_feedback_pack

    append_audit(
        {
            "thesis_id": "feedback-test-001",
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "outcome": "reject",
            "error_code": "agent_sizing_required",
            "gates": {"schema": "pass", "risk": "fail"},
            "warnings": [],
        }
    )

    env = build_feedback_pack(symbol="BTCUSDT", audit_limit=10, signal_limit=5)

    assert env.ok is True
    assert env.data is not None
    assert env.data["audit"]["summary"]["error_codes"]["agent_sizing_required"] == 1
    assert env.data["next_step_policy"] == {
        "may_submit_paper": False,
        "may_write_strategy": False,
        "requires_human_review": True,
    }
    assert env.data["recommendations"][0]["type"] == "thesis_contract"
