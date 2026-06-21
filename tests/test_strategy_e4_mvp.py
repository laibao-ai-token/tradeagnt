"""E4 MVP strategy loop tests."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGE = REPO_ROOT / "scripts" / "tradecat_strategy_manage.py"
COMPARE = REPO_ROOT / "scripts" / "tradecat_strategy_compare.py"
EVOLVE = REPO_ROOT / "scripts" / "tradecat_strategy_evolve.py"
LOOP = REPO_ROOT / "scripts" / "tradecat_strategy_loop.py"
REHEARSAL = REPO_ROOT / "scripts" / "tradecat_strategy_rehearsal.py"


def _assert_agent_submission_commands_safe(submission: dict) -> None:
    forbidden_tokens = {
        "paper",
        "live",
        "tradecat_agent_submit_thesis.py",
        "submit-thesis",
        "trade_submit_thesis",
        "tradecat_strategy_manage.py",
        "strategy_release.py",
        "daemon",
        "--auto-trade",
        "execute",
    }
    for key in ("safe_suggest", "dry_run_verify"):
        command = submission[key]["command_argv"]
        assert command[:2] == ["python3", "scripts/tradecat_strategy_evolve.py"]
        assert "--run-id" not in command
        assert "--mode" in command
        assert command[command.index("--mode") + 1] in {"suggest", "dry_run"}
        for token in forbidden_tokens:
            assert token not in command


def _strategy_yaml(name: str = "Demo Strategy") -> str:
    return f"""name: "{name}"
market: crypto
symbols:
  - BTC_USDT
timeframe: 5m
indicators:
  - name: rsi
    params:
      period: 14
rules:
  - name: RSI bounce
    category: momentum
    subcategory: rsi
    direction: BUY
    strength: 62
    priority: high
    cooldown: 300
    min_volume: 0
    condition:
      type: threshold_cross_up
      field: rsi
      threshold: 35
    message_template: "RSI bounce: {{rsi:.1f}}"
    fields:
      rsi: rsi
  - name: RSI fade
    category: momentum
    subcategory: rsi
    direction: SELL
    strength: 62
    priority: high
    cooldown: 300
    min_volume: 0
    condition:
      type: threshold_cross_down
      field: rsi
      threshold: 65
    message_template: "RSI fade: {{rsi:.1f}}"
    fields:
      rsi: rsi
thresholds:
  min_strength: 50
"""


def _valid_rehearsal_feedback() -> dict:
    return {
        "artifact_type": "rehearsal_feedback",
        "available": True,
        "run_id": "rehearsal_seed",
        "verify_mode": "suggest",
        "loop_run_id": "rehearsal_seed_loop",
        "verify_run_id": "rehearsal_seed_verify",
        "agent_generator_output": "artifacts/strategy-runs/rehearsal_seed/agent_generator_output.json",
        "next_loop_inputs": {
            "previous_rejected_reasons": [
                "underperformed baseline",
                "suggest mode does not run promotion gate",
            ],
            "previous_repair_guidance": ["Keep RSI thresholds between 10 and 90."],
            "previous_risk_summary": {
                "scope": "candidate_set_single_symbol",
                "risk_level": "medium",
                "risk_flags": ["candidate drawdown above baseline"],
                "candidate_count": 2,
                "eligible_count": 1,
                "rejected_count": 1,
                "failed_count": 0,
            },
            "previous_context_health": {
                "quality": "ready",
                "market_data_ready": True,
            },
            "previous_agent_response_validation": (
                "artifacts/strategy-runs/rehearsal_seed_verify/agent_response_validation.json"
            ),
            "previous_agent_generator_output": (
                "artifacts/strategy-runs/rehearsal_seed/agent_generator_output.json"
            ),
        },
        "agent_submission": {
            "safe_suggest": {
                "command_argv": ["python3", "scripts/tradecat_strategy_evolve.py", "--mode", "paper"],
            },
        },
        "current_changed": False,
        "safety": {
            "read_only_feedback": True,
            "external_model_called": False,
            "external_generator_command_executed": False,
            "submission_command_executed": False,
            "paper_allowed": False,
            "live_trading_allowed": False,
            "current_change_allowed": False,
            "watchlist_expansion_allowed": False,
        },
    }


def _valid_rehearsal_chain_summary(feedback_path: str) -> dict:
    return {
        "artifact_type": "rehearsal_chain_summary",
        "available": True,
        "ok": True,
        "run_id": "rehearsal_chain_seed",
        "cycles_requested": 2,
        "cycles_completed": 2,
        "latest_cycle": 2,
        "latest_rehearsal_feedback": feedback_path,
        "next_loop_feedback": feedback_path,
        "cycle_feedback_chain": [
            {
                "cycle": 2,
                "rehearsal_feedback": feedback_path,
                "available": True,
                "rejected_reason_count": 1,
                "repair_guidance_count": 1,
                "risk_summary_available": True,
            }
        ],
        "cycle_summaries": [],
        "latest_next_loop_inputs": {
            "available": True,
            "previous_rejected_reason_count": 1,
            "previous_repair_guidance_count": 1,
            "previous_risk_summary_available": True,
            "previous_risk_level": "medium",
        },
        "latest_agent_next_action": {"action": "generate_candidate_drafts", "blocked": False},
        "promotion": {"activated": False},
        "current_changed": False,
        "safety": {
            "read_only_summary": True,
            "external_model_called": False,
            "external_generator_command_executed": False,
            "submission_command_executed": False,
            "paper_allowed": False,
            "live_trading_allowed": False,
            "current_change_allowed": False,
            "watchlist_expansion_allowed": False,
        },
    }


def _loop_ok_evolve_payload(kwargs: dict) -> tuple[int, dict]:
    run_id = kwargs["run_id"]
    return 0, {
        "ok": True,
        "data": {
            "run_id": run_id,
            "artifact_dir": f"artifacts/strategy-runs/{run_id}",
            "agent_handoff": f"artifacts/strategy-runs/{run_id}/agent_handoff.json",
            "agent_prompt": f"artifacts/strategy-runs/{run_id}/agent_prompt.json",
            "agent_feedback": f"artifacts/strategy-runs/{run_id}/agent_feedback.json",
            "agent_response_template": f"artifacts/strategy-runs/{run_id}/agent_response_template.json",
            "rejected_reasons": {},
            "promotion": {
                "eligible": False,
                "activated": False,
                "gate_passed": False,
                "reason": "suggest mode does not run promotion gate",
            },
            "current_before": "current_release",
            "current_after": "current_release",
            "current_changed": False,
        },
        "error": None,
    }


def _copy_strategy_tree(tmp_path: Path) -> Path:
    src = REPO_ROOT / "config" / "strategies"
    dst = tmp_path / "strategies"
    shutil.copytree(src, dst, symlinks=True)
    return dst


def _run(script: Path, *args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, json.loads(proc.stdout)


def test_strategy_manage_validate_and_dry_run_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_manage_test", MANAGE)
    assert spec and spec.loader
    manage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manage)
    monkeypatch.setattr(manage, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(manage, "CURRENT_LINK", strategies / "current")
    monkeypatch.setattr(manage, "RELEASES_DIR", strategies / "releases")

    valid = manage._execute_validate(argparse.Namespace(strategy="", content=_strategy_yaml()))
    assert valid["ok"] is True

    invalid_path = manage._execute_write(
        argparse.Namespace(strategy="../escape.yaml", content=_strategy_yaml(), note="", dry_run=True)
    )
    assert invalid_path["ok"] is False
    assert invalid_path["error"]["code"] == "invalid_strategy_path"

    dry_run = manage._execute_write(
        argparse.Namespace(strategy="agent_test.yaml", content=_strategy_yaml(), note="", dry_run=True)
    )
    assert dry_run["ok"] is True
    assert dry_run["data"]["written"] is False
    assert not (strategies / "agent_test.yaml").exists()


def test_strategy_manage_snapshot_and_use_release_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_manage_test_use", MANAGE)
    assert spec and spec.loader
    manage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manage)
    monkeypatch.setattr(manage, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(manage, "CURRENT_LINK", strategies / "current")
    monkeypatch.setattr(manage, "RELEASES_DIR", strategies / "releases")

    snap_calls: list[str] = []

    def fake_snapshot(name: str, note: str = "") -> dict:
        snap_calls.append(name)
        return {"ok": True}

    monkeypatch.setattr(manage, "_snapshot_strategy", fake_snapshot)
    existing = strategies / "agent_existing.yaml"
    existing.write_text(_strategy_yaml("Existing"), encoding="utf-8")
    write = manage._execute_write(
        argparse.Namespace(strategy="agent_existing.yaml", content=_strategy_yaml("Updated"), note="", dry_run=False)
    )
    assert write["ok"] is True
    assert write["data"]["snapshot"] is True
    assert snap_calls == ["agent_existing.yaml"]

    release_id = "test_release_use"
    release_dir = strategies / "releases" / release_id
    release_dir.mkdir(parents=True)
    (release_dir / "fast_1m.yaml").write_text(_strategy_yaml("Release"), encoding="utf-8")

    activated: list[str] = []

    def fake_activate(rel_id: str) -> dict:
        activated.append(rel_id)
        return {"ok": True, "release_id": rel_id}

    monkeypatch.setattr(manage, "_activate_release", fake_activate)
    use = manage._execute_use(argparse.Namespace(strategy="", release_id=release_id, note=""))
    assert use["ok"] is True
    assert use["data"]["activation_mode"] == "release"
    assert activated == [release_id]

    invalid = manage._execute_use(argparse.Namespace(strategy="fast_1m", release_id="", note=""))
    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "invalid_strategy_path"


def test_strategy_evolve_dry_run_loop_with_stubbed_compare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")

    current_before = evolve._current_target()

    def fake_manage_write(candidate: dict, *, note: str) -> dict:
        dest = strategies / candidate["strategy"]
        dest.write_text(candidate["content"], encoding="utf-8")
        return {
            "ok": True,
            "tool": "tradecat_strategy_manage",
            "data": {
                "strategy": candidate["strategy"],
                "path": str(dest),
                "written": True,
                "dry_run": False,
            },
            "error": None,
        }

    def fake_compare(**kwargs: object) -> dict:
        strategy_names = list(kwargs["strategies"])  # type: ignore[index]
        assert kwargs["symbol"] == "BTC_USDT"
        ranking = []
        for idx, strategy in enumerate(strategy_names):
            role = "baseline" if idx == 0 else "candidate"
            decision = "baseline" if idx == 0 else ("winner" if idx == 1 else "rejected")
            ranking.append(
                {
                    "strategy": strategy,
                    "role": role,
                    "ok": True,
                    "return_pct": 0.1 + idx,
                    "score": 0.1 + idx,
                    "baseline_delta": 0.2 if decision == "winner" else (-0.1 if decision == "rejected" else 0.0),
                    "trades": 2 + idx,
                    "signals_total": 5 + idx,
                    "score_parts": {
                        "baseline_delta": 0.2 if decision == "winner" else (-0.1 if decision == "rejected" else 0.0),
                        "trade_count": 2 + idx,
                        "signals_total": 5 + idx,
                    },
                    "gate": {"passed": decision != "rejected", "reasons": [] if decision != "rejected" else ["underperformed baseline return"]},
                    "decision": decision,
                    "rejected_reasons": [] if decision != "rejected" else ["underperformed baseline return"],
                }
            )
        return {
            "ok": True,
            "data": {
                "baseline": strategy_names[0],
                "candidates": strategy_names[1:],
                "ranking": ranking,
                "winner": strategy_names[1],
                "rejected_reasons": {strategy_names[-1]: ["underperformed baseline return"]},
            },
            "error": None,
        }

    monkeypatch.setattr(evolve, "_manage_write", fake_manage_write)
    monkeypatch.setattr(evolve, "_compare", fake_compare)
    monkeypatch.setattr(
        evolve,
        "_build_watchlist_ranking",
        lambda **kwargs: [
            {"symbol": "BTC_USDT", "rank": 1, "reason": "target symbol, indicators available"},
            {"symbol": "ETH_USDT", "rank": 2, "reason": "quote available"},
        ],
    )

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--candidate-count",
                "2",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert evolve._current_target() == current_before
    artifact_dir = REPO_ROOT / payload["data"]["artifact_dir"]
    if not artifact_dir.is_dir():
        artifact_dir = tmp_path / "strategy-runs" / payload["data"]["run_id"]
    assert artifact_dir.is_dir()
    assert (artifact_dir / "goal.json").is_file()
    assert (artifact_dir / "context.json").is_file()
    assert (artifact_dir / "candidates.json").is_file()
    assert (artifact_dir / "compare.json").is_file()
    assert (artifact_dir / "decision.json").is_file()
    decision = json.loads((artifact_dir / "decision.json").read_text(encoding="utf-8"))
    assert decision["promotion"]["activated"] is False
    assert decision["promotion"]["eligible"] is False
    assert "paper mode not enabled" in decision["promotion"]["gate_reasons"]
    assert decision["promotion"]["gates"]["candidate_beats_baseline"] is True
    assert decision["current_changed"] is False
    assert payload["data"]["watchlist_ranking"]
    assert {item["symbol"] for item in payload["data"]["watchlist_ranking"]} == {"BTC_USDT", "ETH_USDT"}
    created = [item["strategy"] for item in payload["data"]["candidates"]]
    assert len(created) == 2
    assert all("generator_context" in item for item in payload["data"]["candidates"])
    assert all(item["static_sanity"]["ok"] is True for item in payload["data"]["candidates"])
    assert all((strategies / name).is_file() for name in created)
    assert all((artifact_dir / "candidates" / name).is_file() for name in created)
    candidates_json = json.loads((artifact_dir / "candidates.json").read_text(encoding="utf-8"))
    assert all("generator_context" in item for item in candidates_json["candidates"])
    assert all(item["static_sanity"]["ok"] is True for item in candidates_json["candidates"])
    assert payload["data"]["candidate_retention"]["enabled"] is False


def test_strategy_evolve_promotion_gate_requires_baseline_beat_and_paper_mode() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_promotion", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    candidate_results = [
        {
            "strategy": "candidate.yaml",
            "hypothesis": "Explainable change",
            "changes": ["min_strength 50 -> 60"],
            "validation": {"ok": True, "data": {"written": True}},
        }
    ]
    compare_result = {
        "ok": True,
        "data": {
            "winner": "candidate.yaml",
            "ranking": [
                {
                    "strategy": "candidate.yaml",
                    "decision": "winner",
                    "baseline_delta": 0.0,
                    "trades": 4,
                    "signals_total": 7,
                    "gate": {"passed": True, "reasons": []},
                    "score_parts": {"baseline_delta": 0.0, "trade_count": 4, "signals_total": 7},
                }
            ],
        },
        "previous_repair_guidance": [
            "Set every rule cooldown between 60 and 3600 seconds.",
        ],
    }

    flat = evolve._promotion_gate(
        mode="paper",
        winner="candidate.yaml",
        compare_result=compare_result,
        candidate_results=candidate_results,
    )
    assert flat["eligible"] is False
    assert "candidate did not beat baseline" in flat["gate_reasons"]

    compare_result["data"]["ranking"][0]["baseline_delta"] = 0.15
    compare_result["data"]["ranking"][0]["score_parts"]["baseline_delta"] = 0.15
    dry_run = evolve._promotion_gate(
        mode="dry_run",
        winner="candidate.yaml",
        compare_result=compare_result,
        candidate_results=candidate_results,
    )
    assert dry_run["eligible"] is False
    assert dry_run["activated"] is False
    assert dry_run["gates"]["candidate_beats_baseline"] is True
    assert dry_run["gates"]["paper_mode_enabled"] is False
    assert "paper mode not enabled" in dry_run["gate_reasons"]

    paper = evolve._promotion_gate(
        mode="paper",
        winner="candidate.yaml",
        compare_result=compare_result,
        candidate_results=candidate_results,
    )
    assert paper["eligible"] is True
    assert paper["activated"] is False
    assert paper["gate_reasons"] == []


def test_strategy_evolve_fixed_run_id_keeps_candidates_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_run_id", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")

    monkeypatch.setattr(evolve, "_context_pack", lambda **kwargs: {"quotes": None, "indicators": None, "warnings": []})
    monkeypatch.setattr(
        evolve,
        "_build_watchlist_ranking",
        lambda **kwargs: [{"symbol": "BTC_USDT", "rank": 1, "reason": "target symbol"}],
    )

    def fake_manage_write(candidate: dict, *, note: str) -> dict:
        dest = strategies / candidate["strategy"]
        dest.write_text(candidate["content"], encoding="utf-8")
        return {"ok": True, "data": {"strategy": candidate["strategy"], "written": True}, "error": None}

    def fake_compare(**kwargs: object) -> dict:
        strategy_names = list(kwargs["strategies"])  # type: ignore[index]
        return {
            "ok": True,
            "data": {
                "ranking": [
                    {
                        "strategy": strategy,
                        "role": "baseline" if idx == 0 else "candidate",
                        "decision": "baseline" if idx == 0 else "rejected",
                        "score": 0.0,
                        "rejected_reasons": [] if idx == 0 else ["underperformed baseline return"],
                    }
                    for idx, strategy in enumerate(strategy_names)
                ],
                "winner": None,
                "rejected_reasons": {strategy_names[-1]: ["underperformed baseline return"]},
            },
            "error": None,
        }

    monkeypatch.setattr(evolve, "_manage_write", fake_manage_write)
    monkeypatch.setattr(evolve, "_compare", fake_compare)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT",
                "--candidate-count",
                "2",
                "--run-id",
                "fixed_test_run",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["data"]["run_id"] == "fixed_test_run"
    created = [item["strategy"] for item in payload["data"]["candidates"]]
    assert created == [
        "agent_BTC_USDT_fixed_test_run_01.yaml",
        "agent_BTC_USDT_fixed_test_run_02.yaml",
    ]
    assert all((strategies / name).is_file() for name in created)
    assert payload["data"]["candidate_retention"]["enabled"] is False


def test_strategy_evolve_suggest_writes_agent_prompt_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_suggest_prompt", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(
        evolve,
        "_context_pack",
        lambda **kwargs: {
            "quotes": {"data": [{"ok": True, "price": 100.0}]},
            "indicators": {"data": {"indicators": {"rsi": 50.0}}},
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        evolve,
        "_build_watchlist_ranking",
        lambda **kwargs: [{"symbol": "BTC_USDT", "rank": 1, "reason": "target symbol"}],
    )

    risk_summary = {
        "scope": "candidate_set_single_symbol",
        "risk_level": "high",
        "risk_flags": ["candidate exposure above 80%"],
        "candidate_count": 2,
        "eligible_count": 1,
        "rejected_count": 1,
        "failed_count": 0,
        "max_exposure_pct": 85.0,
        "max_drawdown_pct": 7.5,
        "min_return_pct": -0.25,
        "max_signals_total": 18,
    }
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--market",
                "crypto_spot",
                "--days",
                "3",
                "--timeframe",
                "5m",
                "--provider",
                "gate",
                "--min-strength",
                "61",
                "--mode",
                "suggest",
                "--run-id",
                "suggest_agent_prompt_test",
                "--include-news",
                "--news-limit",
                "8",
                "--news-since-minutes",
                "180",
                "--timeout",
                "45",
                "--previous-risk-summary",
                json.dumps(risk_summary),
                "--previous-repair-guidance",
                json.dumps(["Set every rule cooldown between 60 and 3600 seconds."]),
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    artifact_dir = tmp_path / "strategy-runs" / "suggest_agent_prompt_test"
    prompt_path = artifact_dir / "agent_prompt.json"
    feedback_path = artifact_dir / "agent_feedback.json"
    handoff_path = artifact_dir / "agent_handoff.json"
    template_path = artifact_dir / "agent_response_template.json"
    assert prompt_path.is_file()
    assert feedback_path.is_file()
    assert handoff_path.is_file()
    assert template_path.is_file()
    assert Path(payload["data"]["agent_prompt"]) == prompt_path
    assert Path(payload["data"]["agent_feedback"]) == feedback_path
    assert Path(payload["data"]["agent_handoff"]) == handoff_path
    assert Path(payload["data"]["agent_response_template"]) == template_path
    assert payload["data"]["files"]["agent_prompt"] == payload["data"]["agent_prompt"]
    assert payload["data"]["files"]["agent_feedback"] == payload["data"]["agent_feedback"]
    assert payload["data"]["files"]["agent_handoff"] == payload["data"]["agent_handoff"]
    assert payload["data"]["files"]["agent_response_template"] == payload["data"]["agent_response_template"]
    prompt = json.loads(prompt_path.read_text(encoding="utf-8"))
    feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert prompt["target_symbol"] == "BTC_USDT"
    assert prompt["output_contract"]["submit_via"] == "tradecat_strategy_evolve.py --agent-candidates <json-or-file>"
    assert prompt["output_contract"]["template_artifact"] == "agent_response_template.json"
    assert template["artifact_type"] == "agent_response_template"
    assert template["target_symbol"] == "BTC_USDT"
    assert len(template["template"]["candidates"]) == 2
    assert template["template"]["candidates"][0]["content"].count("BTC_USDT") == 1
    assert any("Return JSON only" in item for item in template["validation_checklist"])
    assert prompt["context"]["watchlist_ranking"][0]["symbol"] == "BTC_USDT"
    assert prompt["context_health"]["quality"] == "ready"
    assert prompt["context_health"]["market_data_ready"] is True
    assert prompt["context"]["context_health"] == prompt["context_health"]
    assert payload["data"]["context_health"] == prompt["context_health"]
    assert prompt["context"]["risk_feedback"]["available"] is True
    assert prompt["context"]["risk_feedback"]["risk_level"] == "high"
    assert "candidate exposure above 80%" in prompt["context"]["risk_feedback"]["risk_flags"]
    assert prompt["context"]["repair_feedback"]["available"] is True
    assert "Set every rule cooldown between 60 and 3600 seconds." in prompt["context"]["repair_feedback"]["items"]
    assert prompt["agent_feedback"]["available"] is True
    assert prompt["agent_feedback"]["context_health"] == prompt["context_health"]
    assert prompt["agent_feedback"]["repair_feedback"]["available"] is True
    assert "fix previous validation repair guidance" in prompt["agent_feedback"]["priority"][0]
    assert prompt["context"]["agent_feedback"] == prompt["agent_feedback"]
    assert prompt["agent_feedback_artifact"] == "agent_feedback.json"
    assert feedback == prompt["agent_feedback"]
    assert handoff["artifact_type"] == "agent_handoff"
    assert handoff["status"] == "suggest_ready"
    assert handoff["target_symbol"] == "BTC_USDT"
    assert handoff["files"]["agent_prompt"] == payload["data"]["agent_prompt"]
    assert handoff["files"]["agent_feedback"] == payload["data"]["agent_feedback"]
    assert handoff["files"]["agent_handoff"] == payload["data"]["agent_handoff"]
    assert handoff["files"]["agent_response_template"] == payload["data"]["agent_response_template"]
    assert handoff["files"]["agent_response"] is None
    assert handoff["files"]["agent_response_validation"] is None
    assert handoff["next_agent_contract"]["required_inputs"] == [
        "agent_prompt",
        "agent_feedback",
        "agent_response_template",
    ]
    assert handoff["next_agent_contract"]["submit_via"] == "tradecat_strategy_evolve.py --agent-candidates <json-or-file>"
    assert handoff["context_health"] == prompt["context_health"]
    assert handoff["next_agent_contract"]["context_health"] == prompt["context_health"]
    assert payload["data"]["agent_next_action"]["action"] == "repair_candidate_drafts"
    assert payload["data"]["agent_next_action"]["readiness"] == "repair_required"
    assert payload["data"]["agent_next_action"]["requires_agent_candidates"] is True
    assert handoff["agent_next_action"] == payload["data"]["agent_next_action"]
    assert handoff["next_agent_contract"]["agent_next_action"] == payload["data"]["agent_next_action"]
    assert payload["data"]["agent_submission"]["artifact_type"] == "agent_submission_hint"
    assert payload["data"]["agent_submission"]["recommended"] == "safe_suggest"
    assert payload["data"]["agent_submission"]["safe_suggest"]["mode"] == "suggest"
    assert payload["data"]["agent_submission"]["dry_run_verify"]["mode"] == "dry_run"
    assert "--agent-candidates" in payload["data"]["agent_submission"]["safe_suggest"]["command_argv"]
    assert "--mode" in payload["data"]["agent_submission"]["dry_run_verify"]["command_argv"]
    assert payload["data"]["agent_submission"]["submission_context"]["strategy"] == "current/fast_1m.yaml"
    assert payload["data"]["agent_submission"]["submission_context"]["symbol"] == "BTC_USDT"
    assert payload["data"]["agent_submission"]["submission_context"]["watchlist"] == ["BTC_USDT", "ETH_USDT"]
    assert payload["data"]["agent_submission"]["submission_context"]["market"] == "crypto_spot"
    assert payload["data"]["agent_submission"]["submission_context"]["days"] == 3
    assert payload["data"]["agent_submission"]["submission_context"]["timeframe"] == "5m"
    assert payload["data"]["agent_submission"]["submission_context"]["provider"] == "gate"
    assert payload["data"]["agent_submission"]["submission_context"]["min_strength"] == 61
    assert payload["data"]["agent_submission"]["submission_context"]["include_news"] is True
    assert payload["data"]["agent_submission"]["submission_context"]["news_limit"] == 8
    assert payload["data"]["agent_submission"]["submission_context"]["news_since_minutes"] == 180
    assert payload["data"]["agent_submission"]["submission_context"]["timeout"] == 45.0
    assert "--days" in payload["data"]["agent_submission"]["dry_run_verify"]["command_argv"]
    assert "--min-strength" in payload["data"]["agent_submission"]["dry_run_verify"]["command_argv"]
    assert "--include-news" in payload["data"]["agent_submission"]["dry_run_verify"]["command_argv"]
    assert "--timeout" in payload["data"]["agent_submission"]["dry_run_verify"]["command_argv"]
    _assert_agent_submission_commands_safe(payload["data"]["agent_submission"])
    assert "paper requires explicit user request" in payload["data"]["agent_submission"]["omitted_args"]["--mode paper"]
    assert handoff["agent_submission"] == payload["data"]["agent_submission"]
    assert handoff["next_agent_contract"]["agent_submission"] == payload["data"]["agent_submission"]
    assert handoff["agent_feedback_summary"]["priority"] == prompt["agent_feedback"]["priority"]
    assert any("Do not change config/strategies/current" in item for item in handoff["safety_constraints"])


def test_strategy_evolve_agent_submission_preserves_request_context() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_submission_context", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    submission = evolve._agent_submission_hint(
        strategy="current/fast_1m.yaml",
        symbol="BTC_USDT",
        watchlist=["BTC_USDT", "ETH_USDT"],
        market="crypto_spot",
        days=3,
        timeframe="5m",
        provider="gate",
        min_strength=62,
        initial_equity=1000.0,
        notional=25.5,
        mode="paper",
        candidate_count=9,
        include_news=True,
        news_limit=8,
        news_since_minutes=180,
        timeout=45.0,
        agent_next_action={"readiness": "ready"},
    )

    context = submission["submission_context"]
    assert context == {
        "strategy": "current/fast_1m.yaml",
        "symbol": "BTC_USDT",
        "watchlist": ["BTC_USDT", "ETH_USDT"],
        "market": "crypto_spot",
        "days": 3,
        "timeframe": "5m",
        "provider": "gate",
        "min_strength": 62,
        "initial_equity": 1000.0,
        "notional": 25.5,
        "candidate_count": 5,
        "include_news": True,
        "news_limit": 8,
        "news_since_minutes": 180,
        "timeout": 45.0,
        "agent_candidates": "<json-or-file>",
    }
    safe_cmd = submission["safe_suggest"]["command_argv"]
    verify_cmd = submission["dry_run_verify"]["command_argv"]
    _assert_agent_submission_commands_safe(submission)

    def value_after(cmd: list[str], flag: str) -> str:
        return cmd[cmd.index(flag) + 1]

    assert value_after(safe_cmd, "--mode") == "suggest"
    assert value_after(verify_cmd, "--mode") == "dry_run"
    assert "paper" not in safe_cmd
    assert "paper" not in verify_cmd
    assert "--run-id" not in safe_cmd
    assert "--run-id" not in verify_cmd
    assert value_after(safe_cmd, "--watchlist") == "BTC_USDT,ETH_USDT"
    assert value_after(safe_cmd, "--market") == "crypto_spot"
    assert value_after(safe_cmd, "--days") == "3"
    assert value_after(safe_cmd, "--timeframe") == "5m"
    assert value_after(safe_cmd, "--provider") == "gate"
    assert value_after(safe_cmd, "--min-strength") == "62"
    assert value_after(safe_cmd, "--candidate-count") == "5"
    assert value_after(safe_cmd, "--initial-equity") == "1000.0"
    assert value_after(safe_cmd, "--notional") == "25.5"
    assert value_after(safe_cmd, "--timeout") == "45.0"
    assert "--include-news" in safe_cmd
    assert value_after(safe_cmd, "--news-limit") == "8"
    assert value_after(safe_cmd, "--news-since-minutes") == "180"
    assert "--agent-candidates" in safe_cmd
    assert value_after(verify_cmd, "--watchlist") == "BTC_USDT,ETH_USDT"
    assert value_after(verify_cmd, "--market") == "crypto_spot"
    assert value_after(verify_cmd, "--days") == "3"
    assert value_after(verify_cmd, "--timeframe") == "5m"
    assert value_after(verify_cmd, "--provider") == "gate"
    assert value_after(verify_cmd, "--min-strength") == "62"
    assert value_after(verify_cmd, "--candidate-count") == "5"
    assert value_after(verify_cmd, "--initial-equity") == "1000.0"
    assert value_after(verify_cmd, "--notional") == "25.5"
    assert value_after(verify_cmd, "--timeout") == "45.0"
    assert "--include-news" in verify_cmd
    assert value_after(verify_cmd, "--news-limit") == "8"
    assert value_after(verify_cmd, "--news-since-minutes") == "180"
    assert "--agent-candidates" in verify_cmd
    assert set(submission["context_preserved_args"]) >= {
        "--strategy",
        "--symbol",
        "--watchlist",
        "--market",
        "--days",
        "--timeframe",
        "--provider",
        "--min-strength",
        "--initial-equity",
        "--notional",
        "--candidate-count",
        "--include-news",
        "--news-limit",
        "--news-since-minutes",
        "--timeout",
    }


def test_strategy_evolve_paper_mode_does_not_activate_when_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_paper_gate_fail", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(evolve, "_context_pack", lambda **kwargs: {"quotes": None, "indicators": None, "warnings": []})
    monkeypatch.setattr(evolve, "_build_watchlist_ranking", lambda **kwargs: [])

    def fake_manage_write(candidate: dict, *, note: str) -> dict:
        dest = strategies / candidate["strategy"]
        dest.write_text(candidate["content"], encoding="utf-8")
        return {"ok": True, "data": {"strategy": candidate["strategy"], "written": True}, "error": None}

    def fake_compare(**kwargs: object) -> dict:
        candidate = list(kwargs["strategies"])[1]  # type: ignore[index]
        return {
            "ok": True,
            "data": {
                "winner": candidate,
                "ranking": [
                    {
                        "strategy": candidate,
                        "decision": "winner",
                        "baseline_delta": 0.0,
                        "trades": 4,
                        "signals_total": 7,
                        "score_parts": {"baseline_delta": 0.0, "trade_count": 4, "signals_total": 7},
                        "gate": {"passed": True, "reasons": []},
                    }
                ],
                "rejected_reasons": {},
            },
            "error": None,
        }

    activated: list[str] = []
    monkeypatch.setattr(evolve, "_manage_write", fake_manage_write)
    monkeypatch.setattr(evolve, "_compare", fake_compare)
    monkeypatch.setattr(evolve, "_manage_use", lambda strategy, *, note: activated.append(strategy) or {"ok": True})

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT",
                "--mode",
                "paper",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert payload["error"]["code"] == "promotion_gate_failed"
    assert payload["data"]["promotion"]["activated"] is False
    assert "candidate did not beat baseline" in payload["data"]["promotion"]["gate_reasons"]
    assert activated == []


def test_strategy_evolve_paper_mode_activates_when_gate_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_paper_activate", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(evolve, "_context_pack", lambda **kwargs: {"quotes": None, "indicators": None, "warnings": []})
    monkeypatch.setattr(evolve, "_build_watchlist_ranking", lambda **kwargs: [])

    current = {"value": "before_release"}
    monkeypatch.setattr(evolve, "_current_target", lambda: current["value"])

    def fake_manage_write(candidate: dict, *, note: str) -> dict:
        dest = strategies / candidate["strategy"]
        dest.write_text(candidate["content"], encoding="utf-8")
        return {"ok": True, "data": {"strategy": candidate["strategy"], "written": True}, "error": None}

    def fake_compare(**kwargs: object) -> dict:
        candidate = list(kwargs["strategies"])[1]  # type: ignore[index]
        return {
            "ok": True,
            "data": {
                "winner": candidate,
                "ranking": [
                    {
                        "strategy": candidate,
                        "decision": "winner",
                        "baseline_delta": 0.25,
                        "trades": 4,
                        "signals_total": 7,
                        "score_parts": {"baseline_delta": 0.25, "trade_count": 4, "signals_total": 7},
                        "gate": {"passed": True, "reasons": []},
                    }
                ],
                "rejected_reasons": {},
            },
            "error": None,
        }

    def fake_manage_use(strategy: str, *, note: str) -> dict:
        current["value"] = "after_release"
        return {
            "ok": True,
            "data": {
                "strategy": strategy,
                "activated": True,
                "release_id": "paper_release_test",
                "current": "config/strategies/releases/paper_release_test",
            },
        }

    monkeypatch.setattr(evolve, "_manage_write", fake_manage_write)
    monkeypatch.setattr(evolve, "_compare", fake_compare)
    monkeypatch.setattr(evolve, "_manage_use", fake_manage_use)
    monkeypatch.setattr(evolve, "_paper_report", lambda symbol: {"ok": True, "data": {"symbol": symbol}})

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT",
                "--mode",
                "paper",
                "--run-id",
                "paper_activate_test",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["data"]["mode"] == "paper"
    assert payload["data"]["promotion"]["eligible"] is True
    assert payload["data"]["promotion"]["activated"] is True
    assert payload["data"]["promotion"]["release_id"] == "paper_release_test"
    assert payload["data"]["paper_report"]["ok"] is True
    assert payload["data"]["current_changed"] is True


def test_strategy_evolve_paper_mode_activation_failure_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_paper_activation_fail", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(evolve, "_context_pack", lambda **kwargs: {"quotes": None, "indicators": None, "warnings": []})
    monkeypatch.setattr(evolve, "_build_watchlist_ranking", lambda **kwargs: [])
    monkeypatch.setattr(evolve, "_current_target", lambda: "before_release")

    def fake_manage_write(candidate: dict, *, note: str) -> dict:
        dest = strategies / candidate["strategy"]
        dest.write_text(candidate["content"], encoding="utf-8")
        return {"ok": True, "data": {"strategy": candidate["strategy"], "written": True}, "error": None}

    def fake_compare(**kwargs: object) -> dict:
        candidate = list(kwargs["strategies"])[1]  # type: ignore[index]
        return {
            "ok": True,
            "data": {
                "winner": candidate,
                "ranking": [
                    {
                        "strategy": candidate,
                        "decision": "winner",
                        "baseline_delta": 0.25,
                        "trades": 4,
                        "signals_total": 7,
                        "score_parts": {"baseline_delta": 0.25, "trade_count": 4, "signals_total": 7},
                        "gate": {"passed": True, "reasons": []},
                    }
                ],
                "rejected_reasons": {},
            },
            "error": None,
        }

    paper_reports: list[str] = []
    monkeypatch.setattr(evolve, "_manage_write", fake_manage_write)
    monkeypatch.setattr(evolve, "_compare", fake_compare)
    monkeypatch.setattr(
        evolve,
        "_manage_use",
        lambda strategy, *, note: {
            "ok": False,
            "error": {"code": "use_failed", "message": "activation refused"},
        },
    )
    monkeypatch.setattr(evolve, "_paper_report", lambda symbol: paper_reports.append(symbol) or {"ok": True})

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT",
                "--mode",
                "paper",
                "--run-id",
                "paper_activation_failure_test",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert payload["error"]["code"] == "paper_activation_failed"
    assert payload["data"]["promotion"]["eligible"] is True
    assert payload["data"]["promotion"]["gate_passed"] is True
    assert payload["data"]["promotion"]["activated"] is False
    assert payload["data"]["promotion"]["activation_failed"] is True
    assert payload["data"]["activation_result"]["ok"] is False
    assert payload["data"]["paper_report"] is None
    assert payload["data"]["current_changed"] is False
    assert paper_reports == []


def test_strategy_loop_runs_three_rounds_and_feeds_rejections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    calls: list[dict] = []

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        index = len(calls)
        rejected = f"round {index} rejection"
        context_health_by_round = {
            1: {
                "available": True,
                "quality": "ready",
                "market_data_ready": True,
                "quote_available": True,
                "indicator_available": True,
                "news_requested": False,
                "news_available": False,
                "missing_inputs": [],
                "warning_sources": [],
            },
            2: {
                "available": True,
                "quality": "limited",
                "market_data_ready": False,
                "quote_available": False,
                "indicator_available": False,
                "news_requested": False,
                "news_available": False,
                "missing_inputs": ["quote", "indicators"],
                "warning_sources": ["quotes", "indicators"],
            },
            3: {
                "available": True,
                "quality": "partial",
                "market_data_ready": False,
                "quote_available": True,
                "indicator_available": False,
                "news_requested": False,
                "news_available": False,
                "missing_inputs": ["indicators"],
                "warning_sources": ["indicators"],
            },
        }
        return 0, {
            "ok": True,
            "data": {
                "run_id": kwargs["run_id"],
                "artifact_dir": f"artifacts/strategy-runs/{kwargs['run_id']}",
                "agent_handoff": f"artifacts/strategy-runs/{kwargs['run_id']}/agent_handoff.json",
                "agent_prompt": f"artifacts/strategy-runs/{kwargs['run_id']}/agent_prompt.json",
                "agent_feedback": f"artifacts/strategy-runs/{kwargs['run_id']}/agent_feedback.json",
                "agent_response_template": f"artifacts/strategy-runs/{kwargs['run_id']}/agent_response_template.json",
                "agent_response": None,
                "agent_response_validation": None,
                "context_health": context_health_by_round[index],
                "agent_next_action": {
                    "action": f"round_{index}_action",
                    "readiness": "ready" if index == 1 else "degraded_context",
                    "candidate_style": "normal" if index == 1 else "conservative",
                    "requires_agent_candidates": True,
                    "reasons": [],
                    "blocked": False,
                },
                "agent_submission": {
                    "artifact_type": "agent_submission_hint",
                    "candidate_payload": "JSON matching agent_response_template.json with a top-level candidates array.",
                    "submission_context": {
                        "strategy": kwargs["strategy"],
                        "symbol": kwargs["symbol"],
                        "watchlist": ["BTC_USDT", "ETH_USDT"],
                        "market": kwargs["market"] or None,
                        "days": kwargs["days"],
                        "timeframe": kwargs["timeframe"] or None,
                        "provider": kwargs["provider"] or None,
                        "min_strength": kwargs["min_strength"],
                        "candidate_count": kwargs["candidate_count"],
                        "include_news": kwargs["include_news"],
                        "news_limit": kwargs["news_limit"],
                        "news_since_minutes": kwargs["news_since_minutes"],
                        "timeout": kwargs["backtest_timeout"],
                        "agent_candidates": "<json-or-file>",
                    },
                    "recommended": "dry_run_verify" if index == 1 else "safe_suggest",
                    "safe_suggest": {
                        "mode": "suggest",
                        "command_argv": ["python3", "scripts/tradecat_strategy_evolve.py", "--mode", "suggest"],
                    },
                    "dry_run_verify": {
                        "mode": "dry_run",
                        "command_argv": ["python3", "scripts/tradecat_strategy_evolve.py", "--mode", "dry_run"],
                    },
                },
                "winner": f"agent_round_{index}.yaml",
                "rejected_reasons": {f"agent_round_{index}_bad.yaml": [rejected]},
                "promotion": {
                    "eligible": False,
                    "activated": False,
                    "gate_passed": False,
                    "reason": "paper mode not enabled",
                },
                "portfolio_risk_summary": {
                    "scope": "candidate_set_single_symbol",
                    "risk_level": "high" if index == 2 else "low",
                    "risk_flags": ["candidate exposure above 80%"] if index == 2 else [],
                    "candidate_count": 2,
                    "eligible_count": 1,
                    "rejected_count": 1,
                    "failed_count": 0,
                    "max_exposure_pct": 85.0 if index == 2 else 40.0,
                    "max_drawdown_pct": 4.0 + index,
                    "min_return_pct": -0.5 if index == 2 else 0.2,
                    "max_signals_total": 12 + index,
                },
                "agent_repair_guidance": [f"round {index} repair guidance"],
                "current_before": "current_release",
                "current_after": "current_release",
                "current_changed": False,
                "next_step": "continue",
            },
            "error": None,
        }

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--days",
                "1",
                "--rounds",
                "3",
                "--candidate-count",
                "2",
                "--run-id",
                "loop_three_round_test",
                "--previous-rejected-reasons",
                "seed rejection",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert payload["data"]["rounds_completed"] == 3
    assert payload["data"]["current_changed"] is False
    assert len(calls) == 3
    assert calls[0]["previous_rejected_reasons"] == ["seed rejection"]
    assert calls[1]["previous_rejected_reasons"] == ["round 1 rejection"]
    assert calls[2]["previous_rejected_reasons"] == ["round 2 rejection"]
    assert calls[0]["previous_risk_summary"] is None
    assert calls[1]["previous_risk_summary"]["risk_level"] == "low"
    assert calls[2]["previous_risk_summary"]["risk_level"] == "high"
    assert calls[0]["previous_repair_guidance"] == []
    assert calls[1]["previous_repair_guidance"] == ["round 1 repair guidance"]
    assert calls[2]["previous_repair_guidance"] == ["round 2 repair guidance"]
    assert calls[0]["run_id"] == "loop_three_round_test_r01"
    assert (tmp_path / "strategy-runs" / "loop_three_round_test" / "loop.json").is_file()
    assert (tmp_path / "strategy-runs" / "loop_three_round_test" / "agent_handoffs.json").is_file()
    assert (tmp_path / "strategy-runs" / "loop_three_round_test" / "agent_generator_task.json").is_file()
    loop_artifact = json.loads((tmp_path / "strategy-runs" / "loop_three_round_test" / "loop.json").read_text(encoding="utf-8"))
    handoffs_artifact = json.loads(
        (tmp_path / "strategy-runs" / "loop_three_round_test" / "agent_handoffs.json").read_text(encoding="utf-8")
    )
    generator_task_artifact = json.loads(
        (tmp_path / "strategy-runs" / "loop_three_round_test" / "agent_generator_task.json").read_text(encoding="utf-8")
    )
    assert loop_artifact["decision"]["rounds_completed"] == 3
    assert payload["data"]["files"]["agent_handoffs"] == payload["data"]["agent_handoffs"]
    assert payload["data"]["files"]["agent_generator_task"] == payload["data"]["agent_generator_task"]
    assert payload["data"]["final_agent_handoff"] == "artifacts/strategy-runs/loop_three_round_test_r03/agent_handoff.json"
    assert payload["data"]["rounds"][0]["agent_handoff"] == "artifacts/strategy-runs/loop_three_round_test_r01/agent_handoff.json"
    assert payload["data"]["rounds"][0]["agent_artifacts"]["agent_prompt"] == (
        "artifacts/strategy-runs/loop_three_round_test_r01/agent_prompt.json"
    )
    assert loop_artifact["decision"]["final_agent_handoff"] == payload["data"]["final_agent_handoff"]
    assert handoffs_artifact["artifact_type"] == "loop_agent_handoffs"
    assert handoffs_artifact["loop_id"] == "loop_three_round_test"
    assert handoffs_artifact["handoff_count"] == 3
    assert handoffs_artifact["final_agent_handoff"] == payload["data"]["final_agent_handoff"]
    assert handoffs_artifact["rounds"][2]["agent_handoff"] == payload["data"]["final_agent_handoff"]
    assert handoffs_artifact["rounds"][2]["repair_guidance"] == ["round 3 repair guidance"]
    assert payload["data"]["rounds"][2]["agent_next_action"]["action"] == "round_3_action"
    assert payload["data"]["final_agent_next_action"] == payload["data"]["rounds"][2]["agent_next_action"]
    assert loop_artifact["decision"]["final_agent_next_action"] == payload["data"]["final_agent_next_action"]
    assert handoffs_artifact["final_agent_next_action"] == payload["data"]["final_agent_next_action"]
    assert handoffs_artifact["rounds"][2]["agent_next_action"] == payload["data"]["final_agent_next_action"]
    assert payload["data"]["final_agent_submission"] == payload["data"]["rounds"][2]["agent_submission"]
    assert loop_artifact["decision"]["final_agent_submission"] == payload["data"]["final_agent_submission"]
    assert handoffs_artifact["final_agent_submission"] == payload["data"]["final_agent_submission"]
    assert handoffs_artifact["rounds"][2]["agent_submission"] == payload["data"]["final_agent_submission"]
    for round_item in payload["data"]["rounds"]:
        _assert_agent_submission_commands_safe(round_item["agent_submission"])
    _assert_agent_submission_commands_safe(payload["data"]["final_agent_submission"])
    continuation = payload["data"]["loop_agent_continuation"]
    assert continuation["artifact_type"] == "loop_agent_continuation"
    assert continuation["available"] is True
    assert continuation["source_round"] == 3
    assert continuation["source_run_id"] == "loop_three_round_test_r03"
    assert continuation["agent_handoff"] == payload["data"]["final_agent_handoff"]
    assert continuation["read_order"] == ["agent_prompt", "agent_feedback", "agent_response_template"]
    assert continuation["artifacts"]["agent_prompt"] == "artifacts/strategy-runs/loop_three_round_test_r03/agent_prompt.json"
    assert continuation["agent_next_action"] == payload["data"]["final_agent_next_action"]
    assert continuation["submission_context"] == payload["data"]["final_agent_submission"]["submission_context"]
    assert continuation["candidate_payload"] == payload["data"]["final_agent_submission"]["candidate_payload"]
    assert continuation["feedback"]["final_rejected_reasons"] == payload["data"]["final_rejected_reasons"]
    assert continuation["feedback"]["final_repair_guidance"] == payload["data"]["final_repair_guidance"]
    assert continuation["feedback"]["final_process_reasons"] == payload["data"]["final_process_reasons"]
    assert continuation["feedback"]["loop_risk_summary"] == payload["data"]["loop_risk_summary"]
    assert continuation["feedback"]["loop_context_health_summary"] == payload["data"]["loop_context_health_summary"]
    assert continuation["do_not_execute_submission_command"] is True
    assert continuation["submission_command_included"] is False
    assert continuation["paper_allowed"] is False
    assert continuation["current_change_allowed"] is False
    assert continuation["live_trading_allowed"] is False
    assert continuation["watchlist_expansion_allowed"] is False
    assert "command_argv" not in json.dumps(continuation, ensure_ascii=False)
    assert loop_artifact["decision"]["loop_agent_continuation"] == continuation
    assert handoffs_artifact["loop_agent_continuation"] == continuation
    generator_task = payload["data"]["loop_agent_generator_task"]
    assert generator_task["artifact_type"] == "loop_agent_generator_task"
    assert generator_task["available"] is True
    assert generator_task["source_round"] == 3
    assert generator_task["source_run_id"] == "loop_three_round_test_r03"
    assert generator_task["read_order"] == continuation["read_order"]
    assert generator_task["input_artifacts"] == continuation["artifacts"]
    assert generator_task["feedback"] == continuation["feedback"]
    assert generator_task["agent_next_action"] == continuation["agent_next_action"]
    assert generator_task["submission_context"] == continuation["submission_context"]
    assert generator_task["output_contract"]["output_path"].endswith(
        "strategy-runs/loop_three_round_test/agent_generator_output.json"
    )
    assert generator_task["output_contract"]["candidate_count"] == 2
    assert generator_task["output_contract"]["candidate_required_fields"] == ["id", "hypothesis", "changes", "content"]
    assert generator_task["file_adapter"]["agent_generator_mode"] == "file"
    assert generator_task["file_adapter"]["agent_generator_output"] == generator_task["output_contract"]["output_path"]
    assert generator_task["file_adapter"]["allowed_verification_modes"] == ["suggest", "dry_run"]
    assert generator_task["external_agent_required"] is True
    assert generator_task["external_model_called"] is False
    assert generator_task["command_executed"] is False
    assert generator_task["paper_allowed"] is False
    assert generator_task["current_change_allowed"] is False
    assert generator_task["live_trading_allowed"] is False
    assert generator_task["watchlist_expansion_allowed"] is False
    assert "command_argv" not in json.dumps(generator_task, ensure_ascii=False)
    assert loop_artifact["decision"]["loop_agent_generator_task"] == generator_task
    assert handoffs_artifact["loop_agent_generator_task"] == generator_task
    assert generator_task_artifact == generator_task
    assert payload["data"]["rounds"][1]["context_health"]["quality"] == "limited"
    loop_context_health = payload["data"]["loop_context_health_summary"]
    assert loop_context_health["scope"] == "loop_single_symbol_context_health"
    assert loop_context_health["round_count"] == 3
    assert loop_context_health["rounds_with_context_health"] == 3
    assert loop_context_health["ready_count"] == 1
    assert loop_context_health["partial_count"] == 1
    assert loop_context_health["limited_count"] == 1
    assert loop_context_health["market_data_ready_count"] == 1
    assert loop_context_health["all_market_data_ready"] is False
    assert loop_context_health["worst_quality"] == "limited"
    assert loop_context_health["missing_inputs"] == ["quote", "indicators"]
    assert loop_context_health["warning_sources"] == ["quotes", "indicators"]
    assert loop_artifact["decision"]["loop_context_health_summary"] == loop_context_health
    assert handoffs_artifact["loop_context_health_summary"] == loop_context_health
    assert handoffs_artifact["rounds"][1]["context_health"]["quality"] == "limited"
    loop_risk = payload["data"]["loop_risk_summary"]
    assert loop_risk["scope"] == "loop_single_symbol_multi_round"
    assert loop_risk["risk_level"] == "high"
    assert loop_risk["round_count"] == 3
    assert loop_risk["rounds_with_risk_summary"] == 3
    assert loop_risk["candidate_count"] == 6
    assert loop_risk["eligible_count"] == 3
    assert loop_risk["rejected_count"] == 3
    assert loop_risk["max_exposure_pct"] == pytest.approx(85.0)
    assert loop_risk["min_return_pct"] == pytest.approx(-0.5)
    assert "candidate exposure above 80%" in loop_risk["risk_flags"]
    assert loop_artifact["decision"]["loop_risk_summary"] == loop_risk
    assert payload["data"]["rounds"][1]["input_risk_summary"]["risk_level"] == "low"
    assert payload["data"]["rounds"][1]["input_repair_guidance"] == ["round 1 repair guidance"]
    assert payload["data"]["final_repair_guidance"] == ["round 3 repair guidance"]
    assert "paper mode not enabled" in payload["data"]["rounds"][0]["process_reasons"]
    assert "paper mode not enabled" in payload["data"]["final_process_reasons"]


def test_strategy_rehearsal_runs_loop_task_and_file_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util
    import yaml

    spec = importlib.util.spec_from_file_location("tradecat_strategy_rehearsal_test", REHEARSAL)
    assert spec and spec.loader
    rehearsal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rehearsal)
    monkeypatch.setattr(rehearsal, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(rehearsal, "_current_target", lambda: "current_release")

    generator_output = tmp_path / "strategy-runs" / "rehearsal_check_loop" / "agent_generator_output.json"
    calls: list[list[str]] = []

    def fake_run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict]:
        calls.append(cmd)
        if "tradecat_strategy_loop.py" in cmd[1]:
            assert "--mode" in cmd
            assert cmd[cmd.index("--mode") + 1] == "suggest"
            return 0, {
                "ok": True,
                "data": {
                    "loop_id": "rehearsal_check_loop",
                    "agent_generator_task": "artifacts/strategy-runs/rehearsal_check_loop/agent_generator_task.json",
                    "loop_agent_generator_task": {
                        "artifact_type": "loop_agent_generator_task",
                        "available": True,
                        "read_order": ["agent_prompt", "agent_feedback", "agent_response_template"],
                        "input_artifacts": {
                            "agent_prompt": "artifacts/strategy-runs/rehearsal_check_loop_r02/agent_prompt.json",
                            "agent_feedback": "artifacts/strategy-runs/rehearsal_check_loop_r02/agent_feedback.json",
                            "agent_response_template": "artifacts/strategy-runs/rehearsal_check_loop_r02/agent_response_template.json",
                        },
                        "feedback": {"final_process_reasons": ["suggest mode does not run promotion gate"]},
                        "agent_next_action": {"action": "generate_conservative_candidates"},
                        "submission_context": {
                            "strategy": "current/fast_1m.yaml",
                            "symbol": "BTC_USDT",
                            "watchlist": ["BTC_USDT", "ETH_USDT"],
                            "market": "crypto_spot",
                            "days": 1,
                            "timeframe": "5m",
                            "provider": "gate",
                            "min_strength": 55,
                            "candidate_count": 2,
                            "include_news": False,
                            "news_limit": 5,
                            "news_since_minutes": 240,
                            "timeout": 60.0,
                        },
                        "output_contract": {
                            "output_path": str(generator_output),
                            "candidate_count": 2,
                        },
                        "paper_allowed": False,
                        "current_change_allowed": False,
                    },
                    "current_changed": False,
                },
                "error": None,
            }
        if "tradecat_strategy_evolve.py" in cmd[1]:
            assert generator_output.is_file()
            generated = json.loads(generator_output.read_text(encoding="utf-8"))
            assert len(generated["candidates"]) == 2
            parsed = [yaml.safe_load(item["content"]) for item in generated["candidates"]]
            assert all(item["symbols"] == ["BTC_USDT"] for item in parsed)
            assert "--agent-generator-mode" in cmd
            assert cmd[cmd.index("--agent-generator-mode") + 1] == "file"
            assert cmd[cmd.index("--agent-generator-output") + 1] == str(generator_output)
            assert cmd[cmd.index("--mode") + 1] == "suggest"
            assert "paper" not in cmd
            return 0, {
                "ok": True,
                "data": {
                    "run_id": "rehearsal_check_verify",
                    "agent_generator": "artifacts/strategy-runs/rehearsal_check_verify/agent_generator.json",
                    "agent_response_validation": "artifacts/strategy-runs/rehearsal_check_verify/agent_response_validation.json",
                    "agent_repair_guidance": ["Keep RSI thresholds between 10 and 90."],
                    "context_health": {"available": True, "quality": "ready", "market_data_ready": True},
                    "agent_next_action": {"action": "generate_candidate_drafts", "readiness": "ready"},
                    "agent_submission": {"artifact_type": "agent_submission_hint", "recommended": "dry_run_verify"},
                    "rejected_reasons": {"agent_bad.yaml": ["underperformed baseline"]},
                    "portfolio_risk_summary": {"scope": "candidate_set_single_symbol", "risk_level": "low"},
                    "candidates": [{"strategy": "agent_good.yaml"}],
                    "promotion": {"activated": False},
                    "current_changed": False,
                },
                "error": None,
            }
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(rehearsal, "_run_json", fake_run_json)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = rehearsal.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--run-id",
                "rehearsal_check",
                "--verify-mode",
                "suggest",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert len(calls) == 2
    assert payload["data"]["loop_run_id"] == "rehearsal_check_loop"
    assert payload["data"]["verify_run_id"] == "rehearsal_check_verify"
    assert payload["data"]["agent_generator_output"] == str(generator_output)
    assert payload["data"]["files"]["rehearsal_feedback"].endswith("strategy-runs/rehearsal_check/rehearsal_feedback.json")
    assert payload["data"]["files"]["rehearsal_chain_summary"].endswith(
        "strategy-runs/rehearsal_check/rehearsal_chain_summary.json"
    )
    assert payload["data"]["agent_generator_output_candidate_count"] == 2
    assert payload["data"]["current_changed"] is False
    assert payload["data"]["promotion"]["activated"] is False
    feedback = payload["data"]["rehearsal_feedback"]
    assert feedback["artifact_type"] == "rehearsal_feedback"
    assert feedback["available"] is True
    assert feedback["verify_mode"] == "suggest"
    assert feedback["loop_run_id"] == "rehearsal_check_loop"
    assert feedback["verify_run_id"] == "rehearsal_check_verify"
    assert feedback["agent_generator_output"] == str(generator_output)
    assert feedback["verify_artifacts"]["agent_generator"] == "artifacts/strategy-runs/rehearsal_check_verify/agent_generator.json"
    assert feedback["verify_artifacts"]["agent_response_validation"] == (
        "artifacts/strategy-runs/rehearsal_check_verify/agent_response_validation.json"
    )
    assert feedback["next_loop_inputs"]["previous_rejected_reasons"] == ["underperformed baseline"]
    assert feedback["next_loop_inputs"]["previous_repair_guidance"] == ["Keep RSI thresholds between 10 and 90."]
    assert feedback["next_loop_inputs"]["previous_risk_summary"]["risk_level"] == "low"
    assert feedback["next_loop_inputs"]["previous_context_health"]["quality"] == "ready"
    assert feedback["next_loop_inputs"]["previous_agent_response_validation"] == (
        "artifacts/strategy-runs/rehearsal_check_verify/agent_response_validation.json"
    )
    assert feedback["agent_next_action"]["readiness"] == "ready"
    assert feedback["candidate_count"] == 1
    assert feedback["safety"]["read_only_feedback"] is True
    assert feedback["safety"]["paper_allowed"] is False
    assert feedback["safety"]["submission_command_executed"] is False
    assert payload["data"]["safety"]["external_model_called"] is False
    assert payload["data"]["safety"]["external_generator_command_executed"] is False
    assert payload["data"]["safety"]["internal_validation_commands_executed"] is True
    assert payload["data"]["safety"]["paper_allowed"] is False
    assert payload["data"]["safety"]["submission_command_executed"] is False
    assert (tmp_path / "strategy-runs" / "rehearsal_check" / "rehearsal.json").is_file()
    assert json.loads((tmp_path / "strategy-runs" / "rehearsal_check" / "rehearsal_feedback.json").read_text(encoding="utf-8")) == feedback
    summary = payload["data"]["rehearsal_chain_summary"]
    assert summary["artifact_type"] == "rehearsal_chain_summary"
    assert summary["ok"] is True
    assert summary["cycles_completed"] == 1
    assert summary["latest_rehearsal_feedback"].endswith("strategy-runs/rehearsal_check/rehearsal_feedback.json")
    assert summary["next_loop_feedback"] == summary["latest_rehearsal_feedback"]
    assert summary["latest_next_loop_inputs"]["previous_rejected_reason_count"] == 1
    assert summary["latest_next_loop_inputs"]["previous_repair_guidance_count"] == 1
    assert summary["latest_next_loop_inputs"]["previous_risk_level"] == "low"
    agent_request = summary["next_agent_generator_request"]
    assert agent_request["available"] is True
    assert agent_request["tool"] == "external_agent_generate_candidates"
    assert agent_request["command_included"] is False
    assert agent_request["params"]["agent_generator_task"] == (
        "artifacts/strategy-runs/rehearsal_check_loop/agent_generator_task.json"
    )
    assert agent_request["params"]["output_path"] == str(generator_output)
    assert agent_request["params"]["candidate_count"] == 2
    assert agent_request["params"]["submission_context"]["watchlist"] == "BTC_USDT,ETH_USDT"
    assert agent_request["verify_request"]["tool"] == "trade_strategy_evolve"
    assert agent_request["verify_request"]["command_included"] is False
    assert agent_request["verify_request"]["params"]["mode"] == "suggest"
    assert agent_request["verify_request"]["params"]["agent_generator_mode"] == "file"
    assert agent_request["verify_request"]["params"]["agent_generator_output"] == str(generator_output)
    assert agent_request["safety"]["paper_allowed"] is False
    assert agent_request["safety"]["watchlist_expansion_allowed"] is False
    assert summary["next_rehearsal_request"]["tool"] == "trade_strategy_rehearsal"
    assert summary["next_rehearsal_request"]["command_included"] is False
    assert summary["next_rehearsal_request"]["params"]["symbol"] == "BTC_USDT"
    assert summary["next_rehearsal_request"]["params"]["previous_rehearsal_chain_summary"].endswith(
        "strategy-runs/rehearsal_check/rehearsal_chain_summary.json"
    )
    assert summary["next_loop_request"]["tool"] == "trade_strategy_loop"
    assert summary["next_loop_request"]["command_included"] is False
    assert summary["next_loop_request"]["params"]["mode"] == "suggest"
    assert summary["next_loop_request"]["params"]["previous_rehearsal_chain_summary"] == (
        summary["next_rehearsal_request"]["params"]["previous_rehearsal_chain_summary"]
    )
    assert summary["latest_agent_next_action"]["readiness"] == "ready"
    assert summary["promotion"]["activated"] is False
    assert summary["safety"]["read_only_summary"] is True
    assert summary["safety"]["paper_allowed"] is False
    assert "command_argv" not in json.dumps(summary, ensure_ascii=False)
    assert json.loads(
        (tmp_path / "strategy-runs" / "rehearsal_check" / "rehearsal_chain_summary.json").read_text(encoding="utf-8")
    ) == summary


def test_strategy_rehearsal_rejects_task_watchlist_expansion_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_rehearsal_test_watchlist_guard", REHEARSAL)
    assert spec and spec.loader
    rehearsal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rehearsal)
    monkeypatch.setattr(rehearsal, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(rehearsal, "_current_target", lambda: "current_release")

    generator_output = tmp_path / "strategy-runs" / "watchlist_guard_loop" / "agent_generator_output.json"
    calls: list[list[str]] = []

    def fake_run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict]:
        calls.append(cmd)
        if "tradecat_strategy_loop.py" in cmd[1]:
            return 0, {
                "ok": True,
                "data": {
                    "loop_id": "watchlist_guard_loop",
                    "agent_generator_task": "artifacts/strategy-runs/watchlist_guard_loop/agent_generator_task.json",
                    "loop_agent_generator_task": {
                        "artifact_type": "loop_agent_generator_task",
                        "available": True,
                        "submission_context": {
                            "strategy": "current/fast_1m.yaml",
                            "symbol": "BTC_USDT",
                            "watchlist": ["BTC_USDT", "ETH_USDT", "SOL_USDT"],
                            "min_strength": 55,
                            "candidate_count": 2,
                        },
                        "output_contract": {"output_path": str(generator_output), "candidate_count": 2},
                        "paper_allowed": False,
                        "current_change_allowed": False,
                    },
                    "current_changed": False,
                },
                "error": None,
            }
        raise AssertionError(f"verify should not run after watchlist expansion: {cmd}")

    monkeypatch.setattr(rehearsal, "_run_json", fake_run_json)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = rehearsal.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--run-id",
                "watchlist_guard",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_agent_generator_task"
    assert "expanded watchlist" in payload["error"]["message"]
    assert len(calls) == 1
    assert not generator_output.exists()
    assert payload["data"]["cycles"][0]["verify_exit_code"] is None
    assert payload["data"]["current_changed"] is False


def test_strategy_rehearsal_fails_if_verify_changes_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_rehearsal_test_current_guard", REHEARSAL)
    assert spec and spec.loader
    rehearsal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rehearsal)
    monkeypatch.setattr(rehearsal, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    current = {"value": "current_release"}
    monkeypatch.setattr(rehearsal, "_current_target", lambda: current["value"])

    generator_output = tmp_path / "strategy-runs" / "current_guard_loop" / "agent_generator_output.json"
    calls: list[list[str]] = []

    def fake_run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict]:
        calls.append(cmd)
        if "tradecat_strategy_loop.py" in cmd[1]:
            return 0, {
                "ok": True,
                "data": {
                    "loop_id": "current_guard_loop",
                    "agent_generator_task": "artifacts/strategy-runs/current_guard_loop/agent_generator_task.json",
                    "loop_agent_generator_task": {
                        "artifact_type": "loop_agent_generator_task",
                        "available": True,
                        "submission_context": {
                            "strategy": "current/fast_1m.yaml",
                            "symbol": "BTC_USDT",
                            "watchlist": ["BTC_USDT"],
                            "min_strength": 55,
                            "candidate_count": 2,
                        },
                        "output_contract": {"output_path": str(generator_output), "candidate_count": 2},
                        "paper_allowed": False,
                        "current_change_allowed": False,
                    },
                    "current_changed": False,
                },
                "error": None,
            }
        if "tradecat_strategy_evolve.py" in cmd[1]:
            assert generator_output.is_file()
            current["value"] = "after_release"
            return 0, {
                "ok": True,
                "data": {
                    "run_id": "current_guard_verify",
                    "agent_repair_guidance": [],
                    "context_health": {"available": True, "quality": "ready"},
                    "agent_next_action": {"action": "generate_candidate_drafts", "readiness": "ready"},
                    "agent_submission": {"artifact_type": "agent_submission_hint", "recommended": "dry_run_verify"},
                    "rejected_reasons": {},
                    "portfolio_risk_summary": {"scope": "candidate_set_single_symbol", "risk_level": "low"},
                    "candidates": [{"strategy": "agent_good.yaml"}],
                    "promotion": {"activated": False},
                    "current_changed": False,
                },
                "error": None,
            }
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(rehearsal, "_run_json", fake_run_json)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = rehearsal.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--run-id",
                "current_guard",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "rehearsal_failed"
    assert len(calls) == 2
    assert payload["data"]["current_changed"] is True
    assert payload["data"]["cycles"][0]["current_changed"] is True
    assert payload["data"]["rehearsal_feedback"]["available"] is False


def test_strategy_rehearsal_cycles_feed_feedback_into_next_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_rehearsal_test_cycles", REHEARSAL)
    assert spec and spec.loader
    rehearsal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rehearsal)
    monkeypatch.setattr(rehearsal, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(rehearsal, "_current_target", lambda: "current_release")

    calls: list[list[str]] = []

    def fake_run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict]:
        calls.append(cmd)
        if "tradecat_strategy_loop.py" in cmd[1]:
            loop_run_id = cmd[cmd.index("--run-id") + 1]
            if loop_run_id.endswith("_c01_loop"):
                assert "--previous-rehearsal-feedback" not in cmd
            if loop_run_id.endswith("_c02_loop"):
                assert "--previous-rehearsal-feedback" in cmd
                feedback_arg = cmd[cmd.index("--previous-rehearsal-feedback") + 1]
                assert feedback_arg.endswith("cycle_01_rehearsal_feedback.json")
                assert Path(feedback_arg).is_file()
            output_path = tmp_path / "strategy-runs" / loop_run_id / "agent_generator_output.json"
            return 0, {
                "ok": True,
                "data": {
                    "loop_id": loop_run_id,
                    "agent_generator_task": f"artifacts/strategy-runs/{loop_run_id}/agent_generator_task.json",
                    "loop_agent_generator_task": {
                        "artifact_type": "loop_agent_generator_task",
                        "available": True,
                        "feedback": {"final_process_reasons": ["suggest mode does not run promotion gate"]},
                        "submission_context": {
                            "strategy": "current/fast_1m.yaml",
                            "symbol": "BTC_USDT",
                            "watchlist": ["BTC_USDT", "ETH_USDT"],
                            "days": 1,
                            "min_strength": 50,
                            "candidate_count": 2,
                            "include_news": False,
                            "news_limit": 5,
                            "news_since_minutes": 240,
                            "timeout": 60.0,
                        },
                        "output_contract": {
                            "output_path": str(output_path),
                            "candidate_count": 2,
                        },
                        "paper_allowed": False,
                        "current_change_allowed": False,
                    },
                    "current_changed": False,
                },
                "error": None,
            }
        if "tradecat_strategy_evolve.py" in cmd[1]:
            generator_output = Path(cmd[cmd.index("--agent-generator-output") + 1])
            assert generator_output.is_file()
            verify_run_id = cmd[cmd.index("--run-id") + 1]
            return 0, {
                "ok": True,
                "data": {
                    "run_id": verify_run_id,
                    "agent_generator": f"artifacts/strategy-runs/{verify_run_id}/agent_generator.json",
                    "agent_response_validation": f"artifacts/strategy-runs/{verify_run_id}/agent_response_validation.json",
                    "agent_repair_guidance": [f"repair from {verify_run_id}"],
                    "context_health": {"available": True, "quality": "ready", "market_data_ready": True},
                    "agent_next_action": {"action": "generate_candidate_drafts", "readiness": "ready"},
                    "agent_submission": {"artifact_type": "agent_submission_hint", "recommended": "dry_run_verify"},
                    "rejected_reasons": {"agent_bad.yaml": [f"rejected by {verify_run_id}"]},
                    "portfolio_risk_summary": {"scope": "candidate_set_single_symbol", "risk_level": "low"},
                    "candidates": [{"strategy": "agent_good.yaml"}],
                    "promotion": {"activated": False},
                    "current_changed": False,
                },
                "error": None,
            }
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(rehearsal, "_run_json", fake_run_json)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = rehearsal.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--run-id",
                "rehearsal_chain",
                "--cycles",
                "2",
                "--verify-mode",
                "suggest",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert len(calls) == 4
    assert payload["data"]["cycles_requested"] == 2
    assert payload["data"]["cycles_completed"] == 2
    assert payload["data"]["loop_run_id"] == "rehearsal_chain_c02_loop"
    assert payload["data"]["verify_run_id"] == "rehearsal_chain_c02_verify"
    assert len(payload["data"]["cycle_feedback_chain"]) == 2
    first_feedback = payload["data"]["cycle_feedback_chain"][0]["rehearsal_feedback"]
    second_feedback = payload["data"]["cycle_feedback_chain"][1]["rehearsal_feedback"]
    assert first_feedback.endswith("cycle_01_rehearsal_feedback.json")
    assert second_feedback.endswith("cycle_02_rehearsal_feedback.json")
    assert payload["data"]["cycle_feedback_chain"][1]["previous_rehearsal_feedback"] == first_feedback
    assert payload["data"]["rehearsal_feedback"]["cycle"] == 2
    assert payload["data"]["rehearsal_feedback"]["previous_rehearsal_feedback"] == first_feedback
    assert payload["data"]["rehearsal_feedback"]["safety"]["paper_allowed"] is False
    summary = payload["data"]["rehearsal_chain_summary"]
    assert summary["artifact_type"] == "rehearsal_chain_summary"
    assert summary["cycles_requested"] == 2
    assert summary["cycles_completed"] == 2
    assert summary["latest_cycle"] == 2
    assert summary["latest_rehearsal_feedback"].endswith("rehearsal_chain/rehearsal_feedback.json")
    assert summary["next_loop_feedback"] == summary["latest_rehearsal_feedback"]
    assert summary["cycle_summaries"][1]["previous_rehearsal_feedback"] == first_feedback
    assert summary["cycle_summaries"][1]["next_loop_inputs"]["previous_rejected_reason_count"] == 1
    assert summary["cycle_summaries"][1]["next_loop_inputs"]["previous_repair_guidance_count"] == 1
    assert summary["latest_next_loop_inputs"]["previous_risk_level"] == "low"
    agent_request = summary["next_agent_generator_request"]
    assert agent_request["available"] is True
    assert agent_request["params"]["agent_generator_task"].endswith(
        "strategy-runs/rehearsal_chain_c02_loop/agent_generator_task.json"
    )
    assert agent_request["params"]["output_path"].endswith(
        "strategy-runs/rehearsal_chain_c02_loop/agent_generator_output.json"
    )
    assert agent_request["verify_request"]["params"]["mode"] == "suggest"
    assert agent_request["verify_request"]["params"]["agent_generator_mode"] == "file"
    assert agent_request["verify_request"]["params"]["agent_generator_output"] == agent_request["params"]["output_path"]
    assert agent_request["safety"]["submission_command_executed"] is False
    assert summary["next_rehearsal_request"]["tool"] == "trade_strategy_rehearsal"
    assert summary["next_rehearsal_request"]["params"]["cycles"] == 2
    assert summary["next_rehearsal_request"]["params"]["previous_rehearsal_chain_summary"].endswith(
        "strategy-runs/rehearsal_chain/rehearsal_chain_summary.json"
    )
    assert summary["next_loop_request"]["tool"] == "trade_strategy_loop"
    assert summary["next_loop_request"]["params"]["mode"] == "suggest"
    assert summary["next_loop_request"]["params"]["previous_rehearsal_chain_summary"] == (
        summary["next_rehearsal_request"]["params"]["previous_rehearsal_chain_summary"]
    )
    assert summary["latest_agent_next_action"]["readiness"] == "ready"
    assert summary["current_changed"] is False
    assert summary["safety"]["read_only_summary"] is True
    assert summary["safety"]["submission_command_executed"] is False
    assert "command_argv" not in json.dumps(summary, ensure_ascii=False)
    assert payload["data"]["current_changed"] is False
    assert (tmp_path / "strategy-runs" / "rehearsal_chain" / "rehearsal_feedback.json").is_file()
    assert json.loads(
        (tmp_path / "strategy-runs" / "rehearsal_chain" / "rehearsal_chain_summary.json").read_text(encoding="utf-8")
    ) == summary


def test_strategy_rehearsal_accepts_chain_summary_as_first_cycle_seed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_rehearsal_test_summary_seed", REHEARSAL)
    assert spec and spec.loader
    rehearsal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rehearsal)
    monkeypatch.setattr(rehearsal, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(rehearsal, "_current_target", lambda: "current_release")

    feedback_path = tmp_path / "seed_rehearsal_feedback.json"
    feedback_path.write_text(json.dumps(_valid_rehearsal_feedback(), ensure_ascii=False), encoding="utf-8")
    summary_path = tmp_path / "seed_rehearsal_chain_summary.json"
    summary_path.write_text(json.dumps(_valid_rehearsal_chain_summary(str(feedback_path)), ensure_ascii=False), encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict]:
        calls.append(cmd)
        if "tradecat_strategy_loop.py" in cmd[1]:
            assert "--previous-rehearsal-chain-summary" in cmd
            assert cmd[cmd.index("--previous-rehearsal-chain-summary") + 1] == str(summary_path)
            assert "--previous-rehearsal-feedback" not in cmd
            output_path = tmp_path / "strategy-runs" / "rehearsal_summary_seed_loop" / "agent_generator_output.json"
            return 0, {
                "ok": True,
                "data": {
                    "loop_id": "rehearsal_summary_seed_loop",
                    "loop_agent_generator_task": {
                        "artifact_type": "loop_agent_generator_task",
                        "available": True,
                        "feedback": {},
                        "submission_context": {
                            "strategy": "current/fast_1m.yaml",
                            "symbol": "BTC_USDT",
                            "watchlist": ["BTC_USDT", "ETH_USDT"],
                            "days": 1,
                            "min_strength": 50,
                            "candidate_count": 2,
                            "include_news": False,
                            "news_limit": 5,
                            "news_since_minutes": 240,
                            "timeout": 60.0,
                        },
                        "output_contract": {
                            "output_path": str(output_path),
                            "candidate_count": 2,
                        },
                    },
                    "current_changed": False,
                },
                "error": None,
            }
        if "tradecat_strategy_evolve.py" in cmd[1]:
            verify_run_id = cmd[cmd.index("--run-id") + 1]
            return 0, {
                "ok": True,
                "data": {
                    "run_id": verify_run_id,
                    "agent_response_validation": f"artifacts/strategy-runs/{verify_run_id}/agent_response_validation.json",
                    "context_health": {"available": True, "quality": "ready", "market_data_ready": True},
                    "agent_next_action": {"action": "generate_candidate_drafts", "readiness": "ready"},
                    "agent_submission": {"artifact_type": "agent_submission_hint"},
                    "rejected_reasons": {},
                    "portfolio_risk_summary": {"scope": "candidate_set_single_symbol", "risk_level": "low"},
                    "candidates": [{"strategy": "agent_good.yaml"}],
                    "promotion": {"activated": False},
                    "current_changed": False,
                },
                "error": None,
            }
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(rehearsal, "_run_json", fake_run_json)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = rehearsal.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--run-id",
                "rehearsal_summary_seed",
                "--cycles",
                "1",
                "--previous-rehearsal-chain-summary",
                str(summary_path),
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert len(calls) == 2
    assert payload["request"]["previous_rehearsal_chain_summary"] == str(summary_path)
    assert payload["data"]["rehearsal_feedback"]["previous_rehearsal_chain_summary"] == str(summary_path)
    assert payload["data"]["cycle_feedback_chain"][0]["previous_rehearsal_chain_summary"] == str(summary_path)
    assert payload["data"]["rehearsal_chain_summary"]["cycle_summaries"][0]["previous_rehearsal_chain_summary"] == str(summary_path)
    assert payload["data"]["rehearsal_chain_summary"]["next_loop_feedback"].endswith("rehearsal_feedback.json")


def test_strategy_loop_seeds_round_one_from_rehearsal_chain_summary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_rehearsal_chain_summary", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    feedback_path = tmp_path / "seed_rehearsal_feedback.json"
    feedback_path.write_text(json.dumps(_valid_rehearsal_feedback(), ensure_ascii=False), encoding="utf-8")
    summary_path = tmp_path / "seed_rehearsal_chain_summary.json"
    summary_path.write_text(json.dumps(_valid_rehearsal_chain_summary(str(feedback_path)), ensure_ascii=False), encoding="utf-8")
    calls: list[dict] = []

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        return _loop_ok_evolve_payload(dict(kwargs))

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--mode",
                "suggest",
                "--rounds",
                "1",
                "--run-id",
                "loop_rehearsal_chain_summary_file",
                "--previous-rehearsal-chain-summary",
                str(summary_path),
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert calls[0]["previous_rejected_reasons"] == ["underperformed baseline"]
    assert calls[0]["previous_repair_guidance"] == ["Keep RSI thresholds between 10 and 90."]
    assert calls[0]["previous_risk_summary"]["risk_level"] == "medium"
    seed = payload["data"]["previous_rehearsal_feedback_inputs"]
    assert seed["loaded"] is True
    assert seed["source"] == str(feedback_path)
    assert seed["chain_summary_source"] == str(summary_path)
    assert seed["chain_summary_run_id"] == "rehearsal_chain_seed"
    assert seed["chain_summary_cycles_completed"] == 2
    assert seed["chain_summary_latest_cycle"] == 2


def test_strategy_loop_rejects_invalid_rehearsal_chain_summary_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_invalid_rehearsal_chain_summary", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    feedback_path = tmp_path / "seed_rehearsal_feedback.json"
    feedback_path.write_text(json.dumps(_valid_rehearsal_feedback(), ensure_ascii=False), encoding="utf-8")
    valid_summary = _valid_rehearsal_chain_summary(str(feedback_path))
    calls: list[dict] = []
    monkeypatch.setattr(loop, "_run_evolve", lambda **kwargs: calls.append(dict(kwargs)) or _loop_ok_evolve_payload(dict(kwargs)))

    def cloned_summary() -> dict:
        return json.loads(json.dumps(valid_summary, ensure_ascii=False))

    with_command = cloned_summary()
    with_command["next_loop_request"] = {"params": {"command_argv": ["python3", "scripts/tradecat_strategy_evolve.py"]}}
    ok_false = cloned_summary()
    ok_false["ok"] = False
    current_changed = cloned_summary()
    current_changed["current_changed"] = True
    paper_allowed = cloned_summary()
    paper_allowed["safety"]["paper_allowed"] = True

    invalid_inputs = [with_command, ok_false, current_changed, paper_allowed]
    for index, summary in enumerate(invalid_inputs, start=1):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = loop.main(
                [
                    "--strategy",
                    "current/fast_1m.yaml",
                    "--symbol",
                    "BTC_USDT",
                    "--mode",
                    "suggest",
                    "--rounds",
                    "1",
                    "--run-id",
                    f"loop_invalid_rehearsal_chain_summary_{index}",
                    "--previous-rehearsal-chain-summary",
                    json.dumps(summary, ensure_ascii=False),
                ]
            )
        payload = json.loads(stdout.getvalue())
        assert code == 1
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_previous_rehearsal_feedback"
        assert payload["data"]["rounds_completed"] == 0
        assert payload["data"]["previous_rehearsal_feedback_inputs"]["loaded"] is False
        assert calls == []


def test_strategy_loop_seeds_round_one_from_rehearsal_feedback_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_rehearsal_feedback_file", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    feedback_path = tmp_path / "rehearsal_feedback.json"
    feedback_path.write_text(json.dumps(_valid_rehearsal_feedback(), ensure_ascii=False), encoding="utf-8")
    calls: list[dict] = []

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        return _loop_ok_evolve_payload(dict(kwargs))

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--mode",
                "suggest",
                "--rounds",
                "1",
                "--run-id",
                "loop_rehearsal_feedback_file",
                "--previous-rejected-reasons",
                "manual rejection",
                "--previous-repair-guidance",
                "manual repair guidance",
                "--previous-rehearsal-feedback",
                str(feedback_path),
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert calls[0]["previous_rejected_reasons"] == ["manual rejection", "underperformed baseline"]
    assert calls[0]["previous_repair_guidance"] == [
        "manual repair guidance",
        "Keep RSI thresholds between 10 and 90.",
    ]
    assert calls[0]["previous_risk_summary"]["risk_level"] == "medium"
    assert payload["request"]["previous_rehearsal_feedback_inputs"]["loaded"] is True
    assert payload["data"]["previous_rehearsal_feedback_inputs"]["verify_run_id"] == "rehearsal_seed_verify"
    assert payload["data"]["rounds"][0]["input_rejected_reasons"] == calls[0]["previous_rejected_reasons"]
    assert payload["data"]["rounds"][0]["input_risk_summary"]["risk_level"] == "medium"
    assert "suggest mode does not run promotion gate" not in calls[0]["previous_rejected_reasons"]


def test_strategy_loop_seeds_round_one_from_rehearsal_feedback_json_string(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_rehearsal_feedback_json", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    calls: list[dict] = []

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        return _loop_ok_evolve_payload(dict(kwargs))

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--mode",
                "suggest",
                "--rounds",
                "1",
                "--run-id",
                "loop_rehearsal_feedback_json",
                "--previous-rehearsal-feedback",
                json.dumps(_valid_rehearsal_feedback(), ensure_ascii=False),
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert calls[0]["previous_rejected_reasons"] == ["underperformed baseline"]
    assert calls[0]["previous_repair_guidance"] == ["Keep RSI thresholds between 10 and 90."]
    assert calls[0]["previous_risk_summary"]["risk_flags"] == ["candidate drawdown above baseline"]
    assert payload["data"]["previous_rehearsal_feedback_inputs"]["loaded"] is True


def test_strategy_loop_rejects_invalid_rehearsal_feedback_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_invalid_rehearsal_feedback", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    calls: list[dict] = []
    monkeypatch.setattr(loop, "_run_evolve", lambda **kwargs: calls.append(dict(kwargs)) or _loop_ok_evolve_payload(dict(kwargs)))

    missing_inputs = _valid_rehearsal_feedback()
    missing_inputs.pop("next_loop_inputs")
    unsafe = _valid_rehearsal_feedback()
    unsafe["safety"] = {**unsafe["safety"], "paper_allowed": True}
    invalid_inputs = [
        "{not json",
        json.dumps(missing_inputs, ensure_ascii=False),
        json.dumps(unsafe, ensure_ascii=False),
    ]

    for index, raw in enumerate(invalid_inputs, start=1):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = loop.main(
                [
                    "--strategy",
                    "current/fast_1m.yaml",
                    "--symbol",
                    "BTC_USDT",
                    "--mode",
                    "suggest",
                    "--rounds",
                    "1",
                    "--run-id",
                    f"loop_invalid_rehearsal_feedback_{index}",
                    "--previous-rehearsal-feedback",
                    raw,
                ]
            )
        payload = json.loads(stdout.getvalue())
        assert code == 1
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_previous_rehearsal_feedback"
        assert payload["data"]["rounds_completed"] == 0
        assert payload["data"]["previous_rehearsal_feedback_inputs"]["loaded"] is False
        assert calls == []


def test_strategy_loop_rehearsal_feedback_input_keeps_safe_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_rehearsal_feedback_safety", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    feedback = _valid_rehearsal_feedback()
    feedback["mode"] = "paper"
    feedback["command_argv"] = ["python3", "scripts/tradecat_agent_submit_thesis.py"]
    feedback["next_loop_inputs"]["command_argv"] = ["python3", "scripts/tradecat_strategy_evolve.py", "--mode", "paper"]
    feedback_path = tmp_path / "rehearsal_feedback_with_commands.json"
    feedback_path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    calls: list[dict] = []

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        return _loop_ok_evolve_payload(dict(kwargs))

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--mode",
                "suggest",
                "--rounds",
                "1",
                "--run-id",
                "loop_rehearsal_feedback_safety",
                "--previous-rehearsal-feedback",
                str(feedback_path),
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert calls[0]["mode"] == "suggest"
    assert "command_argv" not in json.dumps(calls[0], ensure_ascii=False)
    assert payload["data"]["current_changed"] is False
    assert payload["data"]["rounds"][0]["promotion"]["activated"] is False


def test_strategy_loop_separates_process_reasons_from_agent_rejections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_process_reasons", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    calls: list[dict] = []

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        return 0, {
            "ok": True,
            "data": {
                "run_id": kwargs["run_id"],
                "artifact_dir": f"artifacts/strategy-runs/{kwargs['run_id']}",
                "agent_handoff": f"artifacts/strategy-runs/{kwargs['run_id']}/agent_handoff.json",
                "agent_prompt": f"artifacts/strategy-runs/{kwargs['run_id']}/agent_prompt.json",
                "agent_feedback": f"artifacts/strategy-runs/{kwargs['run_id']}/agent_feedback.json",
                "agent_response_template": f"artifacts/strategy-runs/{kwargs['run_id']}/agent_response_template.json",
                "rejected_reasons": {},
                "promotion": {
                    "eligible": False,
                    "activated": False,
                    "gate_passed": False,
                    "gate_reasons": ["suggest mode does not run promotion gate"],
                    "reason": "suggest mode",
                },
                "current_before": "current_release",
                "current_after": "current_release",
                "current_changed": False,
            },
            "error": None,
        }

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--mode",
                "suggest",
                "--rounds",
                "2",
                "--run-id",
                "loop_process_reason_test",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert len(calls) == 2
    assert calls[0]["previous_rejected_reasons"] == []
    assert calls[1]["previous_rejected_reasons"] == []
    assert payload["data"]["final_rejected_reasons"] == []
    assert payload["data"]["final_process_reasons"] == ["suggest mode does not run promotion gate"]
    assert payload["data"]["rounds"][0]["rejected_reasons"] == []
    assert payload["data"]["rounds"][0]["process_reasons"] == ["suggest mode does not run promotion gate"]
    handoffs_artifact = json.loads(
        (tmp_path / "strategy-runs" / "loop_process_reason_test" / "agent_handoffs.json").read_text(encoding="utf-8")
    )
    assert handoffs_artifact["rounds"][0]["rejected_reasons"] == []
    assert handoffs_artifact["rounds"][0]["process_reasons"] == ["suggest mode does not run promotion gate"]
    assert handoffs_artifact["final_process_reasons"] == ["suggest mode does not run promotion gate"]


def test_strategy_loop_feeds_previous_paper_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_paper_feedback", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    calls: list[dict] = []
    report = {
        "ok": True,
        "data": {
            "pnl_pct": -0.12,
            "positions": [],
            "recent_orders": [{"id": "o1"}],
            "recent_rejects": [{"reason": "risk limit"}],
        },
    }

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        index = len(calls)
        return 0, {
            "ok": True,
            "data": {
                "run_id": kwargs["run_id"],
                "winner": f"agent_round_{index}.yaml",
                "rejected_reasons": {},
                "promotion": {"eligible": True, "activated": True, "gate_passed": True},
                "paper_report": report if index == 1 else None,
                "current_changed": False,
            },
            "error": None,
        }

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--rounds",
                "2",
                "--mode",
                "paper",
                "--run-id",
                "loop_paper_feedback_test",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert calls[0]["previous_paper_report"] is None
    assert calls[1]["previous_paper_report"] == report
    assert payload["data"]["rounds"][0]["paper_report"]["available"] is True
    assert payload["data"]["rounds"][1]["input_paper_report"]["available"] is True


def test_strategy_loop_passes_optional_news_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_news", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    calls: list[dict] = []

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        return 0, {
            "ok": True,
            "data": {
                "run_id": kwargs["run_id"],
                "promotion": {"eligible": False, "activated": False, "gate_passed": False},
                "rejected_reasons": {},
                "current_changed": False,
            },
            "error": None,
        }

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--rounds",
                "2",
                "--include-news",
                "--news-limit",
                "3",
                "--news-since-minutes",
                "60",
                "--run-id",
                "loop_news_test",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert len(calls) == 2
    assert all(call["include_news"] is True for call in calls)
    assert all(call["news_limit"] == 3 for call in calls)
    assert all(call["news_since_minutes"] == 60 for call in calls)


def test_strategy_loop_stops_on_round_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_failure", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(loop, "_current_target", lambda: "current_release")

    calls: list[dict] = []

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        calls.append(dict(kwargs))
        if len(calls) == 1:
            return 0, {
                "ok": True,
                "data": {
                    "run_id": kwargs["run_id"],
                    "promotion": {"eligible": False, "activated": False, "gate_passed": False},
                    "rejected_reasons": {"agent_bad.yaml": ["first rejection"]},
                    "current_changed": False,
                },
                "error": None,
            }
        return 1, {
            "ok": False,
            "data": {
                "run_id": kwargs["run_id"],
                "promotion": {"eligible": False, "activated": False, "gate_passed": False},
                "current_changed": False,
            },
            "error": {"code": "compare_failed", "message": "failed"},
        }

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--rounds",
                "3",
                "--run-id",
                "loop_stop_failure_test",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "round_failed"
    assert payload["data"]["rounds_completed"] == 2
    assert len(calls) == 2


def test_strategy_loop_dry_run_fails_if_current_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_loop_test_current_guard", LOOP)
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    current = {"value": "before_release"}
    monkeypatch.setattr(loop, "_current_target", lambda: current["value"])

    def fake_run_evolve(**kwargs: object) -> tuple[int, dict]:
        current["value"] = "after_release"
        return 0, {
            "ok": True,
            "data": {
                "run_id": kwargs["run_id"],
                "promotion": {"eligible": False, "activated": False, "gate_passed": False},
                "current_before": "before_release",
                "current_after": "after_release",
                "current_changed": True,
            },
            "error": None,
        }

    monkeypatch.setattr(loop, "_run_evolve", fake_run_evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = loop.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--rounds",
                "3",
                "--run-id",
                "loop_current_guard_test",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert payload["error"]["code"] == "current_changed"
    assert payload["data"]["rounds_completed"] == 1
    assert payload["data"]["current_changed"] is True


def test_strategy_evolve_generator_uses_context_and_previous_rejections() -> None:
    import importlib.util
    import yaml

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_generator", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    baseline = yaml.safe_load(_strategy_yaml())
    context = {
        "quotes": {"data": [{"price": 100.0}]},
        "indicators": {
            "data": {
                "close": 100.0,
                "indicators": {
                    "rsi": 72.0,
                    "ema_fast": 98.0,
                    "ema_medium": 101.0,
                    "ema_slow": 105.0,
                    "macd_hist": -1.4,
                },
            }
        },
    }

    candidates = evolve._generate_candidates(
        baseline=baseline,
        symbol="BTC_USDT",
        run_id="test_run",
        count=2,
        context=context,
        previous_rejected_reasons=["too many signals"],
    )

    assert len(candidates) == 2
    assert all(candidate["hypothesis"] for candidate in candidates)
    assert all(candidate["changes"] for candidate in candidates)
    assert any("RSI=72.00" in note for note in candidates[0]["generator_context"]["notes"])
    assert candidates[0]["generator_context"]["previous_rejected_reasons"] == ["too many signals"]
    assert any("cooldown 300 -> 600" in change for change in candidates[0]["changes"])
    assert any("min_strength 50 -> 60" in change for change in candidates[0]["changes"])

    low_activity_candidates = evolve._generate_candidates(
        baseline=baseline,
        symbol="BTC_USDT",
        run_id="test_run_low",
        count=1,
        context=context,
        previous_rejected_reasons=["no paper trades"],
    )
    assert any("min_strength 50 -> 45" in change for change in low_activity_candidates[0]["changes"])
    assert any("cooldown 300 -> 180" in change for change in low_activity_candidates[0]["changes"])

    drawdown_candidates = evolve._generate_candidates(
        baseline=baseline,
        symbol="BTC_USDT",
        run_id="test_run_drawdown",
        count=1,
        context=context,
        previous_rejected_reasons=["max drawdown worse than baseline"],
    )
    assert "worse drawdown" in drawdown_candidates[0]["hypothesis"]
    assert drawdown_candidates[0]["generator_context"]["reason_flags"]["drawdown_worse"] is True
    assert any("min_strength 50 -> 60" in change for change in drawdown_candidates[0]["changes"])
    assert any("cooldown 300 -> 600" in change for change in drawdown_candidates[0]["changes"])

    low_win_candidates = evolve._generate_candidates(
        baseline=baseline,
        symbol="BTC_USDT",
        run_id="test_run_win_rate",
        count=1,
        context=context,
        previous_rejected_reasons=["low win rate"],
    )
    assert "weak win rate" in low_win_candidates[0]["hypothesis"]
    assert low_win_candidates[0]["generator_context"]["reason_flags"]["low_win_rate"] is True


def test_strategy_evolve_uses_agent_candidate_drafts() -> None:
    import importlib.util
    import yaml

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_agent_drafts", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    drafts = [
        {
            "id": "agent_a",
            "hypothesis": "Agent draft tightens BTC entries",
            "changes": ["raise min_strength", "force target symbol"],
            "content": _strategy_yaml("Agent A").replace("BTC_USDT", "ETH_USDT"),
        },
        {
            "id": "agent_b",
            "hypothesis": "Agent draft relaxes BTC rebound",
            "changes": ["lower cooldown"],
            "content": _strategy_yaml("Agent B").replace("BTC_USDT", "SOL_USDT"),
        },
    ]

    loaded = evolve._load_agent_candidate_drafts(json.dumps({"candidates": drafts}))
    candidates = evolve._agent_drafts_to_candidates(
        drafts=loaded,
        symbol="BTC_USDT",
        run_id="agent_draft_test",
        context={"indicators": {"data": {"indicators": {"rsi": 48.0}}}},
        previous_rejected_reasons=["underperformed baseline return"],
    )

    assert [candidate["strategy"] for candidate in candidates] == [
        "agent_BTC_USDT_agent_draft_test_01.yaml",
        "agent_BTC_USDT_agent_draft_test_02.yaml",
    ]
    assert all(candidate["generator_context"]["source"] == "agent_draft" for candidate in candidates)
    assert candidates[0]["generator_context"]["agent_candidate_id"] == "agent_a"
    assert candidates[0]["generator_context"]["previous_rejected_reasons"] == ["underperformed baseline return"]
    assert "symbols forced to BTC_USDT" in candidates[0]["generator_context"]["safety_rewrites"]
    parsed = [yaml.safe_load(candidate["content"]) for candidate in candidates]
    assert all(item["symbols"] == ["BTC_USDT"] for item in parsed)

    with pytest.raises(ValueError, match="must include hypothesis"):
        evolve._load_agent_candidate_drafts(
            json.dumps(
                [
                    {"hypothesis": "", "changes": ["x"], "content": _strategy_yaml("Bad A")},
                    {"hypothesis": "ok", "changes": ["x"], "content": _strategy_yaml("Bad B")},
                ]
            )
        )


def test_strategy_evolve_uses_file_agent_generator_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util
    import yaml

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_file_agent_generator", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(
        evolve,
        "_context_pack",
        lambda **kwargs: {
            "quotes": {"data": [{"ok": True, "price": 100.0}]},
            "indicators": {"data": {"indicators": {"rsi": 50.0}}},
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        evolve,
        "_build_watchlist_ranking",
        lambda **kwargs: [{"symbol": "BTC_USDT", "rank": 1, "reason": "target symbol"}],
    )
    generator_output = tmp_path / "agent_generator_output.json"
    generator_output.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "llm_a",
                        "hypothesis": "File adapter tightens entries",
                        "changes": ["raise strength"],
                        "content": _strategy_yaml("Generator A").replace("BTC_USDT", "ETH_USDT"),
                    },
                    {
                        "id": "llm_b",
                        "hypothesis": "File adapter slows repeated signals",
                        "changes": ["raise cooldown"],
                        "content": _strategy_yaml("Generator B").replace("BTC_USDT", "SOL_USDT"),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT,ETH_USDT",
                "--mode",
                "suggest",
                "--run-id",
                "file_agent_generator_test",
                "--agent-generator-mode",
                "file",
                "--agent-generator-output",
                str(generator_output),
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["ok"] is True
    assert payload["request"]["generator_source"] == "agent_generator_file"
    assert payload["request"]["agent_generator"]["enabled"] is True
    assert payload["request"]["agent_candidate_count"] == 2
    assert payload["data"]["current_changed"] is False
    assert payload["data"]["promotion"]["activated"] is False
    assert payload["data"]["agent_generator"] == payload["data"]["files"]["agent_generator"]
    artifact_dir = tmp_path / "strategy-runs" / "file_agent_generator_test"
    generator_artifact = json.loads((artifact_dir / "agent_generator.json").read_text(encoding="utf-8"))
    assert generator_artifact["artifact_type"] == "agent_generator_adapter"
    assert generator_artifact["source"] == "agent_generator_file"
    assert generator_artifact["candidate_source_ids"] == ["llm_a", "llm_b"]
    assert generator_artifact["external_model_called"] is False
    assert generator_artifact["command_executed"] is False
    assert generator_artifact["paper_allowed"] is False
    agent_response = json.loads((artifact_dir / "agent_response.json").read_text(encoding="utf-8"))
    validation = json.loads((artifact_dir / "agent_response_validation.json").read_text(encoding="utf-8"))
    assert agent_response["source"] == "agent_generator_file"
    assert validation["source"] == "agent_generator_file"
    assert validation["status"] == "passed"
    assert all(candidate["generator_context"]["source"] == "agent_generator_file" for candidate in payload["data"]["candidates"])
    parsed = [yaml.safe_load((artifact_dir / "candidates" / candidate["strategy"]).read_text(encoding="utf-8")) for candidate in payload["data"]["candidates"]]
    assert all(item["symbols"] == ["BTC_USDT"] for item in parsed)
    assert payload["data"]["agent_submission"]["dry_run_verify"]["mode"] == "dry_run"
    _assert_agent_submission_commands_safe(payload["data"]["agent_submission"])


def test_strategy_evolve_file_agent_generator_rejects_paper_mode() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_file_agent_generator_paper", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--agent-generator-mode",
                "file",
                "--agent-generator-output",
                "agent_output.json",
                "--mode",
                "paper",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert payload["error"]["code"] == "invalid_arguments"
    assert "limited to suggest/dry_run" in payload["error"]["message"]


def test_strategy_evolve_static_sanity_checks_candidate_bounds() -> None:
    import importlib.util
    import yaml

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_static_sanity", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    valid = evolve._static_sanity_check_candidate(
        {"strategy": "valid.yaml", "content": _strategy_yaml("Valid")},
        symbol="BTC_USDT",
    )
    assert valid["ok"] is True
    assert valid["summary"]["directions"] == ["BUY", "SELL"]

    bad_data = yaml.safe_load(_strategy_yaml("Bad"))
    bad_data["symbols"] = ["ETH_USDT"]
    bad_data["thresholds"]["min_strength"] = 10
    bad_data["rules"][0]["strength"] = 101
    bad_data["rules"][0]["cooldown"] = 10
    bad_data["rules"][0]["condition"]["threshold"] = 99
    invalid = evolve._static_sanity_check_candidate(
        {"strategy": "bad.yaml", "content": yaml.safe_dump(bad_data, allow_unicode=True, sort_keys=False)},
        symbol="BTC_USDT",
    )
    assert invalid["ok"] is False
    assert "strategy symbols must match target symbol only" in invalid["errors"]
    assert any("strength must be between 30 and 95" in error for error in invalid["errors"])
    assert any("cooldown must be between 60 and 3600" in error for error in invalid["errors"])
    assert any("RSI threshold must be between 10 and 90" in error for error in invalid["errors"])
    assert "thresholds.min_strength must be between 30 and 90" in invalid["errors"]


def test_strategy_evolve_agent_candidate_static_sanity_failure_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util
    import yaml

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_static_fail", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(evolve, "_context_pack", lambda **kwargs: {"quotes": None, "indicators": None, "warnings": []})
    monkeypatch.setattr(evolve, "_build_watchlist_ranking", lambda **kwargs: [])

    bad = yaml.safe_load(_strategy_yaml("Agent Bad"))
    bad["rules"][0]["cooldown"] = 10
    good = yaml.safe_load(_strategy_yaml("Agent Good"))
    payload = {
        "candidates": [
            {
                "id": "bad",
                "hypothesis": "Bad cooldown should fail",
                "changes": ["cooldown too low"],
                "content": yaml.safe_dump(bad, allow_unicode=True, sort_keys=False),
            },
            {
                "id": "good",
                "hypothesis": "Valid backup",
                "changes": ["no risky bounds"],
                "content": yaml.safe_dump(good, allow_unicode=True, sort_keys=False),
            },
        ]
    }

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "BTC_USDT",
                "--agent-candidates",
                json.dumps(payload),
                "--run-id",
                "static_sanity_fail_test",
            ]
        )
    result = json.loads(stdout.getvalue())
    assert code == 1
    assert result["error"]["code"] == "candidate_static_sanity_failed"
    assert "cooldown must be between 60 and 3600" in str(result["error"]["details"])
    assert result["data"]["promotion"]["activated"] is False
    assert result["data"]["current_changed"] is False
    assert result["data"]["files"]["agent_response"] == result["data"]["agent_response"]
    assert result["data"]["files"]["agent_response_validation"] == result["data"]["agent_response_validation"]
    assert result["data"]["files"]["agent_handoff"] == result["data"]["agent_handoff"]
    assert result["data"]["agent_next_action"]["action"] == "repair_candidate_drafts"
    assert result["data"]["agent_next_action"]["readiness"] == "repair_required"
    assert result["data"]["agent_submission"]["recommended"] == "safe_suggest"
    assert not (strategies / "agent_BTC_USDT_static_sanity_fail_test_01.yaml").exists()
    decision = json.loads((tmp_path / "strategy-runs" / "static_sanity_fail_test" / "decision.json").read_text(encoding="utf-8"))
    assert decision["ok"] is False
    agent_response = json.loads((tmp_path / "strategy-runs" / "static_sanity_fail_test" / "agent_response.json").read_text(encoding="utf-8"))
    assert agent_response["source"] == "agent_draft"
    assert agent_response["status"] == "accepted_for_validation"
    assert agent_response["target_symbol"] == "BTC_USDT"
    assert agent_response["candidate_count"] == 2
    assert agent_response["accepted_count"] == 2
    assert agent_response["drafts"][0]["source_id"] == "bad"
    assert agent_response["drafts"][0]["strategy"] == "agent_BTC_USDT_static_sanity_fail_test_01.yaml"
    assert agent_response["drafts"][0]["content_sha256"]
    assert "symbols forced to BTC_USDT" in agent_response["drafts"][0]["safety_rewrites"]
    validation = json.loads(
        (tmp_path / "strategy-runs" / "static_sanity_fail_test" / "agent_response_validation.json").read_text(encoding="utf-8")
    )
    assert validation["artifact_type"] == "agent_response_validation"
    assert validation["status"] == "failed"
    assert validation["ready_count"] == 1
    assert validation["failed_count"] == 1
    assert validation["items"][0]["source_id"] == "bad"
    assert validation["items"][0]["status"] == "static_sanity_failed"
    assert validation["items"][0]["yaml_conversion_ok"] is True
    assert "cooldown_bounds" in validation["items"][0]["failure_categories"]
    assert any("cooldown must be between 60 and 3600" in error for error in validation["items"][0]["static_sanity"]["errors"])
    assert "Set every rule cooldown between 60 and 3600 seconds." in validation["items"][0]["repair_hints"]
    assert "Set every rule cooldown between 60 and 3600 seconds." in validation["repair_guidance"]
    assert validation["items"][1]["status"] == "ready_for_write"
    handoff = json.loads((tmp_path / "strategy-runs" / "static_sanity_fail_test" / "agent_handoff.json").read_text(encoding="utf-8"))
    assert handoff["artifact_type"] == "agent_handoff"
    assert handoff["status"] == "candidate_static_sanity_failed"
    assert handoff["files"]["agent_response"] == result["data"]["agent_response"]
    assert handoff["files"]["agent_response_validation"] == result["data"]["agent_response_validation"]
    assert "agent_response_validation" in handoff["next_agent_contract"]["read_order"]
    assert handoff["agent_next_action"] == result["data"]["agent_next_action"]
    assert handoff["next_agent_contract"]["agent_next_action"] == result["data"]["agent_next_action"]
    assert handoff["agent_submission"] == result["data"]["agent_submission"]
    assert handoff["next_agent_contract"]["agent_submission"] == result["data"]["agent_submission"]
    assert "Set every rule cooldown between 60 and 3600 seconds." in handoff["next_agent_contract"]["repair_guidance"]


def test_strategy_evolve_builds_agent_prompt_pack() -> None:
    import importlib.util
    import yaml

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_agent_prompt", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    baseline = yaml.safe_load(_strategy_yaml())
    context = {
        "quotes": {"data": [{"ok": True, "price": 100.0, "provider": "gate", "amount": 1_000_000}]},
        "indicators": {
            "data": {
                "timeframe": "5m",
                "bar_ts": "2026-01-01T00:00:00Z",
                "close": 100.0,
                "indicators": {"rsi": 52.0, "ema_fast": 101.0, "ema_slow": 99.0},
            }
        },
        "watchlist_ranking": [{"symbol": "BTC_USDT", "rank": 1}],
        "previous_risk_summary": {
            "scope": "candidate_set_single_symbol",
            "risk_level": "medium",
            "risk_flags": ["candidate negative return"],
            "candidate_count": 2,
            "eligible_count": 1,
            "rejected_count": 1,
            "failed_count": 0,
            "max_exposure_pct": 55.0,
            "max_drawdown_pct": 6.0,
            "min_return_pct": -0.1,
            "max_signals_total": 20,
        },
        "previous_repair_guidance": [
            "Set every rule cooldown between 60 and 3600 seconds.",
        ],
    }

    pack = evolve._build_agent_prompt_pack(
        run_id="agent_prompt_test",
        strategy="current/fast_1m.yaml",
        baseline=baseline,
        symbol="BTC_USDT",
        watchlist=["BTC_USDT", "ETH_USDT"],
        context=context,
        candidate_count=3,
        previous_rejected_reasons=["too many signals"],
    )

    assert pack["target_symbol"] == "BTC_USDT"
    assert pack["candidate_count"] == 3
    assert pack["output_contract"]["schema"]["properties"]["candidates"]["minItems"] == 2
    assert pack["output_contract"]["template_artifact"] == "agent_response_template.json"
    assert "content" in pack["output_contract"]["schema"]["properties"]["candidates"]["items"]["required"]
    assert any("Do not expand the watchlist" in item for item in pack["safety_constraints"])
    assert pack["baseline"]["rule_summary"]["rule_count"] == 2
    assert pack["context"]["quote"]["price"] == pytest.approx(100.0)
    assert pack["context"]["indicators"]["values"]["rsi"] == pytest.approx(52.0)
    assert pack["context_health"]["quality"] == "ready"
    assert pack["context_health"]["market_data_ready"] is True
    assert pack["context"]["context_health"] == pack["context_health"]
    assert pack["context"]["risk_feedback"]["risk_level"] == "medium"
    assert "candidate negative return" in pack["context"]["risk_feedback"]["risk_flags"]
    assert pack["context"]["repair_feedback"]["available"] is True
    assert "Set every rule cooldown between 60 and 3600 seconds." in pack["context"]["repair_feedback"]["items"]
    assert pack["agent_feedback"]["available"] is True
    assert pack["agent_feedback"]["context_health"] == pack["context_health"]
    assert pack["agent_feedback_artifact"] == "agent_feedback.json"
    assert "address previous rejected reasons" in pack["agent_feedback"]["priority"]
    assert pack["agent_feedback"]["previous_rejected_reasons"] == ["too many signals"]
    assert pack["context"]["agent_feedback"] == pack["agent_feedback"]
    assert pack["previous_rejected_reasons"] == ["too many signals"]


def test_strategy_evolve_context_health_marks_missing_market_context() -> None:
    import importlib.util
    import yaml

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_context_health", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    baseline = yaml.safe_load(_strategy_yaml())
    context = {
        "quotes": {"data": [{"ok": False, "price": None}]},
        "indicators": {"data": {}},
        "warnings": [{"source": "quotes"}, {"source": "indicators"}],
    }

    pack = evolve._build_agent_prompt_pack(
        run_id="context_health_test",
        strategy="current/fast_1m.yaml",
        baseline=baseline,
        symbol="BTC_USDT",
        watchlist=["BTC_USDT"],
        context=context,
        candidate_count=2,
        previous_rejected_reasons=[],
    )

    health = pack["context_health"]
    assert health["quality"] == "limited"
    assert health["market_data_ready"] is False
    assert health["quote_available"] is False
    assert health["indicator_available"] is False
    assert health["missing_inputs"] == ["quote", "indicators"]
    assert health["warning_sources"] == ["quotes", "indicators"]
    assert pack["context"]["context_health"] == health
    assert pack["agent_feedback"]["context_health"] == health
    assert "market context is incomplete" in pack["agent_feedback"]["priority"][0]
    assert any("context_health.market_data_ready" in item for item in pack["generation_guidance"])


def test_strategy_evolve_generator_uses_previous_paper_report() -> None:
    import importlib.util
    import yaml

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_paper_feedback", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    baseline = yaml.safe_load(_strategy_yaml())
    context = {
        "quotes": {"data": [{"price": 100.0}]},
        "indicators": {
            "data": {
                "close": 100.0,
                "indicators": {"rsi": 52.0, "ema_fast": 101.0, "ema_medium": 100.0, "ema_slow": 99.0},
            }
        },
        "previous_paper_report": {
            "ok": True,
            "data": {
                "pnl_pct": -0.5,
                "positions": [],
                "recent_orders": [{"id": "o1"}],
                "recent_rejects": [{"reason": "risk limit"}],
            },
        },
    }

    candidates = evolve._generate_candidates(
        baseline=baseline,
        symbol="BTC_USDT",
        run_id="paper_feedback_test",
        count=1,
        context=context,
        previous_rejected_reasons=[],
    )

    notes = candidates[0]["generator_context"]["notes"]
    assert any("paper_pnl_pct=-0.5000" in note for note in notes)
    assert any("paper_recent_rejects=1" in note for note in notes)
    assert candidates[0]["generator_context"]["paper_feedback"]["negative_pnl"] is True
    assert candidates[0]["generator_context"]["paper_feedback"]["has_rejects"] is True
    assert "Paper feedback shows rejected trades" in candidates[0]["hypothesis"]


def test_strategy_evolve_generator_uses_optional_news_context() -> None:
    import importlib.util
    import yaml

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_news_context", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    baseline = yaml.safe_load(_strategy_yaml())
    context = {
        "quotes": {"data": [{"price": 100.0}]},
        "indicators": {
            "data": {
                "close": 100.0,
                "indicators": {"rsi": 52.0, "ema_fast": 101.0, "ema_medium": 100.0, "ema_slow": 99.0},
            }
        },
        "news": {
            "ok": True,
            "data": [
                {
                    "title": "BTC ETF inflows rise",
                    "summary": "Fund flows improved",
                    "symbols": ["BTC_USDT"],
                    "category": "macro",
                    "provider": "rss",
                }
            ],
        },
    }

    candidates = evolve._generate_candidates(
        baseline=baseline,
        symbol="BTC_USDT",
        run_id="news_context_test",
        count=1,
        context=context,
        previous_rejected_reasons=[],
    )

    gen_ctx = candidates[0]["generator_context"]
    assert gen_ctx["news_feedback"]["available"] is True
    assert gen_ctx["news_feedback"]["article_count"] == 1
    assert any("news_articles=1" in note for note in gen_ctx["notes"])
    assert any("BTC ETF inflows rise" in note for note in gen_ctx["notes"])

    empty_news_candidates = evolve._generate_candidates(
        baseline=baseline,
        symbol="BTC_USDT",
        run_id="empty_news_context_test",
        count=1,
        context={**context, "news": {"ok": True, "data": []}},
        previous_rejected_reasons=[],
    )
    assert any("news_articles=0" in note for note in empty_news_candidates[0]["generator_context"]["notes"])


def test_strategy_evolve_context_pack_includes_news_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_context_news", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    news_calls: list[tuple[str, int, int]] = []

    def fake_run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict]:
        if "tradecat_get_quotes.py" in cmd[1]:
            return 0, {"ok": True, "data": [{"symbol": "BTC_USDT", "ok": True, "price": 100.0}]}
        if "tradecat_get_indicators.py" in cmd[1]:
            return 0, {"ok": True, "data": {"indicators": {"rsi": 50.0}}}
        raise AssertionError(f"unexpected command: {cmd}")

    def fake_news_context(symbol: str, *, limit: int, since_minutes: int) -> dict:
        news_calls.append((symbol, limit, since_minutes))
        return {"ok": True, "data": [{"title": "BTC headline", "symbols": [symbol]}]}

    monkeypatch.setattr(evolve, "_run_json", fake_run_json)
    monkeypatch.setattr(evolve, "_news_context", fake_news_context)

    context = evolve._context_pack(
        symbol="BTC_USDT",
        market="",
        timeframe="",
        provider="",
        include_news=True,
        news_limit=2,
        news_since_minutes=30,
    )

    assert news_calls == [("BTC_USDT", 2, 30)]
    assert context["news"]["ok"] is True
    assert context["news_feedback"]["article_count"] == 1


def test_strategy_evolve_watchlist_ranking_uses_user_watchlist_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_watchlist", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)

    requested_commands: list[list[str]] = []

    def fake_run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict]:
        requested_commands.append(cmd)
        return (
            0,
            {
                "ok": True,
                "data": [
                    {
                        "ok": True,
                        "request_symbol": "BTC_USDT",
                        "symbol": "BTC_USDT",
                        "amount": 100_000_000,
                        "volume": 2000,
                    },
                    {
                        "ok": True,
                        "request_symbol": "ETH_USDT",
                        "symbol": "ETH_USDT",
                        "amount": 50_000_000,
                        "volume": 5000,
                    },
                ],
            },
        )

    monkeypatch.setattr(evolve, "_run_json", fake_run_json)
    context = {
        "indicators": {
            "data": {
                "indicators": {
                    "rsi": 50,
                }
            }
        }
    }

    ranking = evolve._build_watchlist_ranking(
        watchlist=["BTC_USDT", "ETH_USDT"],
        target_symbol="BTC_USDT",
        context=context,
        market="crypto_spot",
        provider="gate",
    )

    assert [item["symbol"] for item in ranking] == ["BTC_USDT", "ETH_USDT"]
    assert ranking[0]["indicator_available"] is True
    assert ranking[1]["indicator_available"] is None
    assert requested_commands
    assert "--symbols" in requested_commands[0]
    assert requested_commands[0][requested_commands[0].index("--symbols") + 1] == "BTC_USDT,ETH_USDT"
    assert "SOL_USDT" not in " ".join(requested_commands[0])


def test_strategy_evolve_cleanup_only_removes_old_root_agent_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_cleanup", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    for existing in strategies.glob("agent_*.y*ml"):
        existing.unlink()

    keep_latest = strategies / "agent_BTC_USDT_20260608_new_BTC_USDT_01.yaml"
    delete_old = strategies / "agent_BTC_USDT_20260607_old_BTC_USDT_01.yaml"
    manual = strategies / "manual_strategy.yaml"
    current_like_dir = tmp_path / "current_like"
    current_like_dir.mkdir()
    nested_current = current_like_dir / "agent_should_not_delete.yaml"
    release_dir = strategies / "releases" / "cleanup_test"
    release_dir.mkdir(parents=True)
    nested_release = release_dir / "agent_should_not_delete.yaml"
    artifact_candidate = tmp_path / "strategy-runs" / "cleanup_test" / "candidates" / "agent_should_not_delete.yaml"
    artifact_candidate.parent.mkdir(parents=True)
    artifact_candidate.write_text(_strategy_yaml("Artifact Candidate"), encoding="utf-8")
    for idx, path in enumerate([delete_old, keep_latest, manual, nested_current, nested_release]):
        path.write_text(_strategy_yaml(path.stem), encoding="utf-8")
        timestamp = 1_700_000_000 + idx
        path.touch()
        os.utime(path, (timestamp, timestamp))

    result = evolve._cleanup_old_candidates(keep_last_runs=1)

    assert result["enabled"] is True
    assert [Path(item).name for item in result["deleted"]] == [delete_old.name]
    assert not delete_old.exists()
    assert keep_latest.exists()
    assert manual.exists()
    assert nested_current.exists()
    assert nested_release.exists()
    assert artifact_candidate.exists()


def test_strategy_evolve_failure_writes_decision_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util

    strategies = _copy_strategy_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("tradecat_strategy_evolve_test_failure", EVOLVE)
    assert spec and spec.loader
    evolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evolve)
    monkeypatch.setattr(evolve, "STRATEGIES_ROOT", strategies)
    monkeypatch.setattr(evolve, "ARTIFACTS_ROOT", tmp_path / "strategy-runs")
    monkeypatch.setattr(evolve, "_context_pack", lambda **kwargs: {"quotes": None, "indicators": None, "warnings": []})
    monkeypatch.setattr(evolve, "_build_watchlist_ranking", lambda **kwargs: [])

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = evolve.main(
            [
                "--strategy",
                "current/fast_1m.yaml",
                "--symbol",
                "BTC_USDT",
                "--watchlist",
                "ETH_USDT",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 1
    artifact_dir = tmp_path / "strategy-runs" / payload["data"]["run_id"]
    assert (artifact_dir / "goal.json").is_file()
    assert (artifact_dir / "decision.json").is_file()
    decision = json.loads((artifact_dir / "decision.json").read_text(encoding="utf-8"))
    assert decision["ok"] is False
    assert decision["promotion"]["activated"] is False


def test_strategy_evolve_cli_rejects_watchlist_mismatch() -> None:
    code, payload = _run(
        EVOLVE,
        "--strategy",
        "current/fast_1m.yaml",
        "--symbol",
        "BTC_USDT",
        "--watchlist",
        "ETH_USDT",
    )
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "symbol_not_in_watchlist"


def test_paper_sim_outputs_risk_metrics() -> None:
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from tradecat.core.backtest.paper_sim import simulate_paper_trades

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    signals = [
        SimpleNamespace(timestamp=t0, strength=60, symbol="BTC_USDT", direction="BUY", price=100),
        SimpleNamespace(timestamp=t0 + timedelta(minutes=30), strength=60, symbol="BTC_USDT", direction="SELL", price=90),
        SimpleNamespace(timestamp=t0 + timedelta(minutes=60), strength=60, symbol="BTC_USDT", direction="BUY", price=100),
        SimpleNamespace(timestamp=t0 + timedelta(minutes=120), strength=60, symbol="BTC_USDT", direction="SELL", price=120),
    ]

    result = simulate_paper_trades(
        signals,  # type: ignore[arg-type]
        market="crypto",
        initial_cash=10_000,
        notional_per_trade=1_000,
        min_strength=50,
    )

    assert result["closed_trade_count"] == 2
    assert result["winning_trades"] == 1
    assert result["losing_trades"] == 1
    assert result["win_rate_pct"] == pytest.approx(50.0)
    assert result["max_drawdown_pct"] > 0
    assert result["avg_hold_minutes"] == pytest.approx(45.0)
    assert result["max_hold_minutes"] == pytest.approx(60.0)
    assert result["exposure_minutes"] == pytest.approx(90.0)
    assert result["exposure_pct"] == pytest.approx(75.0)
    assert result["equity_curve"]


def test_bridge_backtest_parser_extracts_risk_metrics() -> None:
    import importlib.util

    bridge = REPO_ROOT / "scripts" / "bridge_backtest.py"
    spec = importlib.util.spec_from_file_location("bridge_backtest_test", bridge)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    parsed = module._parse_backtest_stdout(
        """Backtest [crypto_spot]: BTC_USDT @ 5m
Provider: gate | Fetching up to 50 bars (~1d)...
Loaded 50 rows
------------------------------------------------------------
Signal Results
  Total signals:       4
  BUY:     2  |  SELL:    2
  Strength >= 50: 4
------------------------------------------------------------
Paper Simulation
  Trades:        4
  Closed Trades: 2
  Win Rate:      50.00%
  Max Drawdown:  10.25%
  Avg Hold:      45.00 min
  Exposure:      75.00%
  Realized PnL:  100.00
  NAV:           10100.00
  Return:        1.00%
  (notional=1000 USDT per trade)
"""
    )

    assert parsed["paper"]["closed_trades"] == 2
    assert parsed["paper"]["win_rate_pct"] == pytest.approx(50.0)
    assert parsed["paper"]["max_drawdown_pct"] == pytest.approx(10.25)
    assert parsed["paper"]["avg_hold_minutes"] == pytest.approx(45.0)
    assert parsed["paper"]["exposure_pct"] == pytest.approx(75.0)


def test_bridge_backtest_diagnostic_details_add_context() -> None:
    import importlib.util

    bridge = REPO_ROOT / "scripts" / "bridge_backtest.py"
    spec = importlib.util.spec_from_file_location("bridge_backtest_test_diagnostics", bridge)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    details = module._diagnostic_details(
        request_payload={
            "strategy": "candidate.yaml",
            "symbol": "BTC_USDT",
            "market": "crypto_spot",
            "timeframe": "5m",
            "provider": "gate",
            "days": 1,
            "mode": "scan",
        },
        tradecat_bin=".venv/bin/tradecat",
        child_argv=["--mode", "scan", "--strategy", "candidate.yaml"],
        exit_code=2,
        stdout="Usage: tradecat backtest [OPTIONS]\nNo such option: --bad\n",
        stderr="Backtest error:\n",
    )

    assert details["strategy"] == "candidate.yaml"
    assert details["symbol"] == "BTC_USDT"
    assert details["exit_code"] == 2
    assert "strategy=candidate.yaml" in details["diagnostic_summary"]
    assert "symbol=BTC_USDT" in details["diagnostic_summary"]
    assert "No such option: --bad" in details["diagnostic_summary"]
    assert "Backtest error:" not in details["diagnostic_summary"]


def test_strategy_compare_outputs_score_parts_and_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_compare_test", COMPARE)
    assert spec and spec.loader
    compare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compare)

    fake_results = {
        "baseline.yaml": {
            "strategy": "baseline.yaml",
            "ok": True,
            "signals_total": 8,
            "trades": 3,
            "return_pct": 0.2,
            "max_drawdown_pct": 2.0,
            "win_rate_pct": 66.67,
            "avg_hold_minutes": 20.0,
            "exposure_pct": 40.0,
        },
        "candidate_bad.yaml": {
            "strategy": "candidate_bad.yaml",
            "ok": True,
            "signals_total": 12,
            "trades": 4,
            "return_pct": 0.1,
            "max_drawdown_pct": 8.5,
            "win_rate_pct": 25.0,
            "avg_hold_minutes": 300.0,
            "exposure_pct": 85.0,
        },
        "candidate_good.yaml": {
            "strategy": "candidate_good.yaml",
            "ok": True,
            "signals_total": 6,
            "trades": 3,
            "return_pct": 0.2,
            "max_drawdown_pct": 1.0,
            "win_rate_pct": 80.0,
            "avg_hold_minutes": 30.0,
            "exposure_pct": 35.0,
        },
        "candidate_failed.yaml": {
            "strategy": "candidate_failed.yaml",
            "ok": False,
            "signals_total": None,
            "trades": None,
            "return_pct": None,
            "max_drawdown_pct": None,
            "win_rate_pct": None,
            "avg_hold_minutes": None,
            "exposure_pct": None,
            "error": {
                "code": "backtest_failed",
                "message": "tradecat backtest exited with code 1",
                "details": {
                    "stderr_tail": [
                        "Backtest error: invalid threshold value",
                    ],
                },
            },
        },
    }

    def fake_run_backtest(**kwargs: object) -> dict:
        return fake_results[str(kwargs["strategy"])]

    monkeypatch.setattr(compare, "_run_backtest", fake_run_backtest)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = compare.main(
            [
                "--strategies",
                "baseline.yaml,candidate_bad.yaml,candidate_good.yaml,candidate_failed.yaml",
                "--symbol",
                "BTC_USDT",
                "--days",
                "1",
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert code == 0

    ranking = payload["data"]["ranking"]
    assert all("score_parts" in item for item in ranking)
    assert all("gate" in item for item in ranking)
    portfolio_risk = payload["data"]["portfolio_risk_summary"]
    assert portfolio_risk["scope"] == "candidate_set_single_symbol"
    assert portfolio_risk["risk_level"] == "high"
    assert portfolio_risk["candidate_count"] == 3
    assert portfolio_risk["rejected_count"] == 2
    assert portfolio_risk["max_exposure_pct"] == pytest.approx(85.0)
    assert portfolio_risk["max_drawdown_pct"] == pytest.approx(8.5)
    assert "candidate exposure above 80%" in portfolio_risk["risk_flags"]
    assert "one or more candidate backtests failed" in portfolio_risk["risk_flags"]

    baseline_item = next(item for item in ranking if item["strategy"] == "baseline.yaml")
    assert baseline_item["decision"] == "baseline"
    assert baseline_item["gate"]["passed"] is True
    assert baseline_item["rejected_reasons"] == []

    bad = next(item for item in ranking if item["strategy"] == "candidate_bad.yaml")
    assert bad["baseline_delta"] == pytest.approx(-0.1)
    assert bad["score_parts"]["max_drawdown_pct"] == pytest.approx(8.5)
    assert bad["score_parts"]["baseline_max_drawdown_pct"] == pytest.approx(2.0)
    assert bad["score_parts"]["drawdown_delta"] == pytest.approx(6.5)
    assert bad["score_parts"]["win_rate_pct"] == pytest.approx(25.0)
    assert bad["score_parts"]["return_drawdown_ratio"] == pytest.approx(0.011765)
    assert bad["score_parts"]["baseline_return_drawdown_ratio"] == pytest.approx(0.1)
    assert bad["score_parts"]["return_drawdown_ratio_delta"] == pytest.approx(-0.088235)
    assert bad["score_parts"]["return_drawdown_bonus"] == pytest.approx(0.0)
    assert bad["score_parts"]["drawdown_penalty"] == pytest.approx(0.17)
    assert bad["score_parts"]["avg_hold_minutes"] == pytest.approx(300.0)
    assert bad["score_parts"]["exposure_pct"] == pytest.approx(85.0)
    assert bad["score_parts"]["exposure_penalty"] == pytest.approx(0.07)
    assert bad["score_parts"]["hold_penalty"] == pytest.approx(0.03)
    assert bad["decision"] == "rejected"
    assert "underperformed baseline return" in bad["gate"]["reasons"]
    assert "max drawdown worse than baseline" in bad["gate"]["reasons"]
    assert "paper exposure too high" in bad["gate"]["reasons"]

    good = next(item for item in ranking if item["strategy"] == "candidate_good.yaml")
    assert good["decision"] == "winner"
    assert good["score_parts"]["return_drawdown_ratio"] == pytest.approx(0.2)
    assert good["score_parts"]["return_drawdown_ratio_delta"] == pytest.approx(0.1)
    assert good["score_parts"]["return_drawdown_bonus"] == pytest.approx(0.002)

    failed = next(item for item in ranking if item["strategy"] == "candidate_failed.yaml")
    assert failed["decision"] == "rejected"
    assert failed["gate"]["passed"] is False
    assert "backtest failed" in failed["rejected_reasons"]
    assert "invalid threshold value" in failed["failure_reason"]


def test_strategy_compare_failure_reason_falls_back_to_diagnostics() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tradecat_strategy_compare_test_diagnostics", COMPARE)
    assert spec and spec.loader
    compare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compare)

    reason = compare._failure_reason(
        {
            "strategy": "candidate_empty_error.yaml",
            "ok": False,
            "error": {
                "code": "backtest_failed",
                "message": "tradecat backtest exited with code 2",
                "details": {
                    "strategy": "candidate_empty_error.yaml",
                    "symbol": "BTC_USDT",
                    "market": "crypto_spot",
                    "timeframe": "5m",
                    "provider": "gate",
                    "days": 1,
                    "exit_code": 2,
                    "stderr_tail": ["Backtest error:"],
                    "stdout_tail": ["No such option: --bad"],
                    "diagnostic_summary": (
                        "backtest failed (strategy=candidate_empty_error.yaml, "
                        "symbol=BTC_USDT, exit_code=2); detail=No such option: --bad"
                    ),
                },
            },
        }
    )

    assert reason is not None
    assert "candidate_empty_error.yaml" in reason
    assert "BTC_USDT" in reason
    assert "exit_code=2" in reason
    assert "No such option: --bad" in reason
    assert "Backtest error: |" not in reason
