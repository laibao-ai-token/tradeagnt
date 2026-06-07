"""Concurrent submit-thesis tests for P0-1 race fix.

Race (before fix): same ``thesis_id`` submitted N times concurrently →
all pass ``find_accepted`` (audit not yet written) → all call
``engine.long/short`` → multiple positions opened.

Fix: SQLite ``INSERT OR IGNORE`` claim lock in
``tradecat.agent.lock``. First caller wins; concurrent callers return
``idempotent_replay`` (in_flight or already_accepted).
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = (
    REPO.parent / "pi" / "docs" / "trade-agent" / "20260527-V2" / "examples" / "agent_trade_thesis.example.json"
)
if not EXAMPLE.is_file():
    EXAMPLE = Path("/public/home/laibao/pkg/dcu/codex/trade-agent/pi/docs/trade-agent/20260527-V2/examples/agent_trade_thesis.example.json")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PAPER_REPO_TYPE", "memory")
    monkeypatch.setenv("TRADEAGNT_AUDIT_PATH", str(tmp_path / "agent_audit.jsonl"))
    monkeypatch.setenv("TRADEAGNT_AGENT_LOCK_PATH", str(tmp_path / ".agent_thesis_lock.db"))
    from tradecat.agent import lock

    lock.reset_for_tests()


def _load_example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _write_thesis(t: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(t), encoding="utf-8")


def test_concurrent_same_id_single_accept(tmp_path: Path) -> None:
    """N=10 threads, same thesis_id → exactly 1 accept, 9 idempotent_replay."""
    from tradecat.agent.submit import submit_thesis

    n = 10
    thesis = _load_example()
    thesis["thesis_id"] = "concurrent-same-001"
    path = tmp_path / "test_concurrent_same.json"
    _write_thesis(thesis, path)

    barrier = threading.Barrier(n)
    results: list = []
    errors: list[BaseException] = []

    def submit_once() -> None:
        try:
            barrier.wait(timeout=5)
            env = submit_thesis(input_path=path, dry_run=False)
            results.append(env)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(submit_once) for _ in range(n)]
        for f in futures:
            f.result()

    assert not errors, f"线程异常: {errors}"

    filled_accept = [r for r in results if r.ok and r.data and r.data.get("action") == "filled" and not r.data.get("idempotent")]
    replayed = [r for r in results if r.ok and r.data and r.data.get("idempotent")]

    assert len(filled_accept) == 1, f"应有 1 个 filled accept，实际 {len(filled_accept)}"
    assert len(replayed) == n - 1, f"应有 {n - 1} 个 idempotent_replay，实际 {len(replayed)}"

    accept_in_flight = [r for r in replayed if "in_flight" in (r.warnings or [])]
    accept_already = [r for r in replayed if "in_flight" not in (r.warnings or [])]
    assert len(accept_in_flight) + len(accept_already) == n - 1


def test_concurrent_different_ids_all_accept(tmp_path: Path) -> None:
    """N=5 threads, distinct thesis_ids → all 5 accept (no false blocking)."""
    from tradecat.agent.submit import submit_thesis

    n = 5
    barrier = threading.Barrier(n)
    results: list = []
    errors: list[BaseException] = []

    def submit_once(idx: int) -> None:
        try:
            thesis = _load_example()
            thesis["thesis_id"] = f"concurrent-diff-{idx:03d}"
            path = tmp_path / f"test_concurrent_diff_{idx:03d}.json"
            _write_thesis(thesis, path)
            barrier.wait(timeout=5)
            env = submit_thesis(input_path=path, dry_run=False)
            results.append(env)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(submit_once, i) for i in range(n)]
        for f in futures:
            f.result()

    assert not errors, f"线程异常: {errors}"
    accept_count = sum(1 for r in results if r.ok and r.data and r.data.get("action") == "filled" and not r.data.get("idempotent"))
    assert accept_count == n, f"应有 {n} 个 accept，实际 {accept_count}"


def test_lock_in_flight_blocks_second_claim() -> None:
    """Manual: claim once, claim again → second sees in_flight."""
    from tradecat.agent.lock import claim

    result1 = claim("manual-001")
    assert result1["acquired"] is True
    assert result1["reason"] == "claimed"

    result2 = claim("manual-001")
    assert result2["acquired"] is False
    assert result2["reason"] == "in_flight"

    from tradecat.agent.lock import release

    release("manual-001", accepted=True)

    result3 = claim("manual-001")
    assert result3["acquired"] is False
    assert result3["reason"] == "already_accepted"


def test_lock_release_reject_allows_reclaim() -> None:
    """release(accepted=False) deletes the in-flight row, so corrected thesis can re-claim."""
    from tradecat.agent.lock import claim, release

    r1 = claim("reject-001")
    assert r1["acquired"] is True

    r2 = claim("reject-001")
    assert r2["acquired"] is False
    assert r2["reason"] == "in_flight"

    release("reject-001", accepted=False)

    r3 = claim("reject-001")
    assert r3["acquired"] is True, f"应能重 claim，实际: {r3}"
    assert r3["reason"] == "claimed"


def test_submit_thesis_reject_releases_for_retry(tmp_path: Path) -> None:
    """Submit a broken thesis (schema reject) → lock is released → can re-claim with fixed thesis."""
    from tradecat.agent.lock import claim
    from tradecat.agent.submit import submit_thesis

    thesis = _load_example()
    thesis["thesis_id"] = "retry-001"
    del thesis["paper_intent"]
    path = tmp_path / "test_retry_reject.json"
    _write_thesis(thesis, path)

    env_reject = submit_thesis(input_path=path, dry_run=False)
    assert env_reject.ok is False

    r = claim("retry-001")
    assert r["acquired"] is True, f"reject 后锁应已释放，实际: {r}"
