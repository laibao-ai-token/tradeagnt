"""E3 agent harness smoke tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = (
    REPO.parent / "pi" / "docs" / "trade-agent" / "20260527-V2" / "examples" / "agent_trade_thesis.example.json"
)
if not EXAMPLE.is_file():
    EXAMPLE = Path("/public/home/laibao/pkg/dcu/codex/trade-agent/pi/docs/trade-agent/20260527-V2/examples/agent_trade_thesis.example.json")


@pytest.fixture(autouse=True)
def _memory_paper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PAPER_REPO_TYPE", "memory")
    monkeypatch.setenv("TRADEAGNT_AUDIT_PATH", str(tmp_path / "agent_audit.jsonl"))


def _load_example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_thesis_validate_dry_run() -> None:
    from tradecat.agent.submit import validate_thesis_only

    env = validate_thesis_only(input_path=EXAMPLE)
    assert env.ok is True
    assert env.data is not None
    assert env.data.get("action") == "dry_run"


def test_submit_watch_only(tmp_path: Path) -> None:
    from tradecat.agent.submit import submit_thesis

    thesis = _load_example()
    thesis["thesis_id"] = "test-watch-only-001"
    thesis["direction"] = "WATCH_ONLY"
    path = tmp_path / "test_watch.json"
    path.write_text(json.dumps(thesis), encoding="utf-8")
    env = submit_thesis(input_path=path, dry_run=False)
    assert env.ok is True
    assert env.data is not None
    assert env.data.get("action") == "watch_only"


def test_submit_rejects_missing_sizing(tmp_path: Path) -> None:
    from tradecat.agent.submit import submit_thesis

    thesis = _load_example()
    thesis["thesis_id"] = "test-reject-sizing-001"
    del thesis["paper_intent"]
    path = tmp_path / "test_bad.json"
    path.write_text(json.dumps(thesis), encoding="utf-8")
    env = submit_thesis(input_path=path, dry_run=False)
    assert env.ok is False
    assert env.error is not None
    assert env.error.get("code") in ("agent_sizing_required", "agent_thesis_schema_invalid")
