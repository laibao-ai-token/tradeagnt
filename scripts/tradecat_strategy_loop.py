#!/usr/bin/env python3
"""Multi-round E4/E5 strategy loop runner.

This script intentionally stays thin: each round delegates candidate generation,
validation, comparison, and optional paper activation to tradecat_strategy_evolve.py.
The loop runner only carries feedback between rounds and enforces fail-closed
safety around current strategy changes.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EVOLVE_SCRIPT = REPO_ROOT / "scripts" / "tradecat_strategy_evolve.py"
STRATEGIES_ROOT = REPO_ROOT / "config" / "strategies"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "strategy-runs"
TOOL_NAME = "tradecat_strategy_loop"


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _base_response() -> dict[str, Any]:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "ts": _utc_now_iso(),
        "request": {},
        "data": None,
        "error": None,
    }


def _safe_run_id(raw: str, symbol: str) -> str:
    value = (raw or "").strip()
    if not value:
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        value = f"loop_{stamp}_{symbol}"
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    value = value.strip("._-")
    if not value:
        raise ValueError("run id is empty")
    if value in {".", ".."} or ".." in value:
        raise ValueError("run id may not contain '..'")
    if len(value) > 96:
        raise ValueError("run id is too long")
    return value


def _current_target() -> str | None:
    current = STRATEGIES_ROOT / "current"
    if current.is_symlink():
        return str(current.resolve(strict=False))
    if current.exists():
        return str(current.resolve(strict=False))
    return None


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load_json_object_arg(raw: str, *, label: str) -> dict[str, Any] | None:
    value = (raw or "").strip()
    if not value:
        return None
    if value.startswith("{"):
        parsed = json.loads(value)
    else:
        path = Path(value)
        if not path.is_absolute():
            path = REPO_ROOT / path
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except OSError as e:
            raise ValueError(f"{label} file cannot be read: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _strict_string_list(raw: Any, *, label: str, limit: int = 12) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"{label} must contain only strings")
        value = item.strip()
        if value:
            values.append(value)
    return values[:limit]


def _strict_dict(raw: Any, *, label: str) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a JSON object")
    return raw


def _strict_optional_string(raw: Any, *, label: str) -> str | None:
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a string or null")
    return raw


def _load_previous_rehearsal_feedback(raw: str) -> dict[str, Any]:
    payload = _load_json_object_arg(raw, label="previous rehearsal feedback")
    if payload is None:
        raise ValueError("previous rehearsal feedback is empty")
    if payload.get("artifact_type") != "rehearsal_feedback":
        raise ValueError("previous rehearsal feedback artifact_type must be rehearsal_feedback")
    if payload.get("available") is not True:
        raise ValueError("previous rehearsal feedback must have available=true")
    if payload.get("verify_mode") not in {"suggest", "dry_run"}:
        raise ValueError("previous rehearsal feedback verify_mode must be suggest or dry_run")
    if payload.get("current_changed") is not False:
        raise ValueError("previous rehearsal feedback must have current_changed=false")

    safety = payload.get("safety")
    if not isinstance(safety, dict):
        raise ValueError("previous rehearsal feedback safety must be a JSON object")
    if safety.get("read_only_feedback") is not True:
        raise ValueError("previous rehearsal feedback safety.read_only_feedback must be true")
    for key in (
        "external_model_called",
        "external_generator_command_executed",
        "submission_command_executed",
        "paper_allowed",
        "live_trading_allowed",
        "current_change_allowed",
        "watchlist_expansion_allowed",
    ):
        if safety.get(key) is not False:
            raise ValueError(f"previous rehearsal feedback safety.{key} must be false")

    inputs = payload.get("next_loop_inputs")
    if not isinstance(inputs, dict):
        raise ValueError("previous rehearsal feedback next_loop_inputs must be a JSON object")
    for key in (
        "previous_rejected_reasons",
        "previous_repair_guidance",
        "previous_risk_summary",
        "previous_context_health",
        "previous_agent_response_validation",
        "previous_agent_generator_output",
    ):
        if key not in inputs:
            raise ValueError(f"previous rehearsal feedback next_loop_inputs.{key} is required")

    return {
        "source": raw,
        "run_id": payload.get("run_id"),
        "loop_run_id": payload.get("loop_run_id"),
        "verify_run_id": payload.get("verify_run_id"),
        "verify_mode": payload.get("verify_mode"),
        "previous_rejected_reasons": _strict_string_list(
            inputs.get("previous_rejected_reasons"),
            label="next_loop_inputs.previous_rejected_reasons",
        ),
        "previous_repair_guidance": _strict_string_list(
            inputs.get("previous_repair_guidance"),
            label="next_loop_inputs.previous_repair_guidance",
        ),
        "previous_risk_summary": _strict_dict(
            inputs.get("previous_risk_summary"),
            label="next_loop_inputs.previous_risk_summary",
        ),
        "previous_context_health": _strict_dict(
            inputs.get("previous_context_health"),
            label="next_loop_inputs.previous_context_health",
        ),
        "previous_agent_response_validation": _strict_optional_string(
            inputs.get("previous_agent_response_validation"),
            label="next_loop_inputs.previous_agent_response_validation",
        ),
        "previous_agent_generator_output": _strict_optional_string(
            inputs.get("previous_agent_generator_output"),
            label="next_loop_inputs.previous_agent_generator_output",
        ),
    }


def _load_previous_rehearsal_chain_summary(raw: str) -> dict[str, Any]:
    payload = _load_json_object_arg(raw, label="previous rehearsal chain summary")
    if payload is None:
        raise ValueError("previous rehearsal chain summary is empty")
    if payload.get("artifact_type") != "rehearsal_chain_summary":
        raise ValueError("previous rehearsal chain summary artifact_type must be rehearsal_chain_summary")
    if payload.get("available") is not True:
        raise ValueError("previous rehearsal chain summary must have available=true")
    if payload.get("ok") is not True:
        raise ValueError("previous rehearsal chain summary must have ok=true")
    if payload.get("current_changed") is not False:
        raise ValueError("previous rehearsal chain summary must have current_changed=false")
    if "command_argv" in json.dumps(payload, ensure_ascii=False):
        raise ValueError("previous rehearsal chain summary must not contain command_argv")

    safety = payload.get("safety")
    if not isinstance(safety, dict):
        raise ValueError("previous rehearsal chain summary safety must be a JSON object")
    if safety.get("read_only_summary") is not True:
        raise ValueError("previous rehearsal chain summary safety.read_only_summary must be true")
    for key in (
        "external_model_called",
        "external_generator_command_executed",
        "submission_command_executed",
        "paper_allowed",
        "live_trading_allowed",
        "current_change_allowed",
        "watchlist_expansion_allowed",
    ):
        if safety.get(key) is not False:
            raise ValueError(f"previous rehearsal chain summary safety.{key} must be false")

    next_loop_feedback = payload.get("next_loop_feedback")
    if not isinstance(next_loop_feedback, str) or not next_loop_feedback.strip():
        raise ValueError("previous rehearsal chain summary next_loop_feedback must be a non-empty string")
    return {
        "source": raw,
        "run_id": payload.get("run_id"),
        "cycles_completed": payload.get("cycles_completed"),
        "latest_cycle": payload.get("latest_cycle"),
        "next_loop_feedback": next_loop_feedback.strip(),
    }


def _load_previous_feedback_seed(
    *,
    feedback_raw: str,
    chain_summary_raw: str,
) -> dict[str, Any] | None:
    if feedback_raw and chain_summary_raw:
        raise ValueError("--previous-rehearsal-feedback and --previous-rehearsal-chain-summary are mutually exclusive")
    if chain_summary_raw:
        summary = _load_previous_rehearsal_chain_summary(chain_summary_raw)
        seed = _load_previous_rehearsal_feedback(str(summary["next_loop_feedback"]))
        seed["chain_summary_source"] = summary["source"]
        seed["chain_summary_run_id"] = summary.get("run_id")
        seed["chain_summary_cycles_completed"] = summary.get("cycles_completed")
        seed["chain_summary_latest_cycle"] = summary.get("latest_cycle")
        return seed
    if feedback_raw:
        return _load_previous_rehearsal_feedback(feedback_raw)
    return None


def _merge_feedback_strings(target: list[str], incoming: list[str]) -> list[str]:
    seen = set(target)
    for item in incoming:
        _append_reason(target, seen, item)
    return target


def _previous_rehearsal_feedback_summary(seed: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(seed, dict):
        return {"loaded": False}
    context_health = seed.get("previous_context_health") if isinstance(seed.get("previous_context_health"), dict) else {}
    return {
        "loaded": True,
        "source": seed.get("source"),
        "run_id": seed.get("run_id"),
        "loop_run_id": seed.get("loop_run_id"),
        "verify_run_id": seed.get("verify_run_id"),
        "verify_mode": seed.get("verify_mode"),
        "rejected_reason_count": len(seed.get("previous_rejected_reasons") or []),
        "repair_guidance_count": len(seed.get("previous_repair_guidance") or []),
        "risk_summary_available": bool(seed.get("previous_risk_summary")),
        "context_health_quality": context_health.get("quality"),
        "agent_response_validation": seed.get("previous_agent_response_validation"),
        "agent_generator_output": seed.get("previous_agent_generator_output"),
        "chain_summary_source": seed.get("chain_summary_source"),
        "chain_summary_run_id": seed.get("chain_summary_run_id"),
        "chain_summary_cycles_completed": seed.get("chain_summary_cycles_completed"),
        "chain_summary_latest_cycle": seed.get("chain_summary_latest_cycle"),
        "read_only_feedback": True,
    }


def _run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return 124, {
            "ok": False,
            "error": _error_payload(
                "timeout",
                "child command timed out",
                {"timeout": timeout, "stdout_tail": (e.stdout or "").splitlines()[-10:], "stderr_tail": (e.stderr or "").splitlines()[-10:]},
            ),
        }
    except Exception as e:  # noqa: BLE001
        return 1, {"ok": False, "error": _error_payload("subprocess_failed", str(e))}

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.returncode or 1, {
            "ok": False,
            "error": _error_payload(
                "invalid_json",
                "child command did not return JSON",
                {"stdout_tail": result.stdout.splitlines()[-10:], "stderr_tail": result.stderr.splitlines()[-10:]},
            ),
        }
    return result.returncode, payload


def _run_evolve(
    *,
    strategy: str,
    symbol: str,
    watchlist: str,
    market: str,
    days: int,
    timeframe: str,
    provider: str,
    min_strength: int,
    initial_equity: float | None,
    notional: float | None,
    candidate_count: int,
    mode: str,
    run_id: str,
    previous_rejected_reasons: list[str],
    previous_paper_report: dict[str, Any] | None,
    previous_risk_summary: dict[str, Any] | None,
    previous_repair_guidance: list[str],
    include_news: bool,
    news_limit: int,
    news_since_minutes: int,
    cleanup_old_candidates: bool,
    keep_candidates: bool,
    keep_last_runs: int,
    backtest_timeout: float,
    round_timeout: float,
) -> tuple[int, dict[str, Any]]:
    args = [
        sys.executable,
        str(EVOLVE_SCRIPT),
        "--strategy",
        strategy,
        "--symbol",
        symbol,
        "--days",
        str(days),
        "--candidate-count",
        str(candidate_count),
        "--min-strength",
        str(min_strength),
        "--mode",
        mode,
        "--run-id",
        run_id,
        "--timeout",
        str(backtest_timeout),
    ]
    if watchlist:
        args.extend(["--watchlist", watchlist])
    if market:
        args.extend(["--market", market])
    if timeframe:
        args.extend(["--timeframe", timeframe])
    if provider:
        args.extend(["--provider", provider])
    if initial_equity is not None:
        args.extend(["--initial-equity", str(initial_equity)])
    if notional is not None:
        args.extend(["--notional", str(notional)])
    if previous_rejected_reasons:
        args.extend(["--previous-rejected-reasons", "; ".join(previous_rejected_reasons)])
    if previous_paper_report:
        args.extend(["--previous-paper-report", json.dumps(previous_paper_report, ensure_ascii=False)])
    if previous_risk_summary:
        args.extend(["--previous-risk-summary", json.dumps(previous_risk_summary, ensure_ascii=False)])
    if previous_repair_guidance:
        args.extend(["--previous-repair-guidance", "; ".join(previous_repair_guidance)])
    if include_news:
        args.append("--include-news")
        args.extend(["--news-limit", str(news_limit), "--news-since-minutes", str(news_since_minutes)])
    if cleanup_old_candidates:
        args.append("--cleanup-old-candidates")
    if keep_candidates:
        args.append("--keep-candidates")
    args.extend(["--keep-last-runs", str(keep_last_runs)])

    return _run_json(args, timeout=round_timeout)


PROCESS_REASONS = {
    "paper mode not enabled",
    "suggest mode does not run promotion gate",
}


def _reason_text(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def _is_process_reason(raw: Any) -> bool:
    return _reason_text(raw).lower() in PROCESS_REASONS


def _append_reason(reasons: list[str], seen: set[str], raw: Any) -> None:
    reason = _reason_text(raw)
    if not reason or _is_process_reason(reason):
        return
    if reason not in seen:
        seen.add(reason)
        reasons.append(reason)


def _append_process_reason(reasons: list[str], seen: set[str], raw: Any) -> None:
    reason = _reason_text(raw)
    if not reason or not _is_process_reason(reason):
        return
    if reason not in seen:
        seen.add(reason)
        reasons.append(reason)


def _collect_rejected_reasons(payload: dict[str, Any], *, limit: int = 12) -> list[str]:
    data = payload.get("data") or {}
    compare_data = ((data.get("compare") or {}).get("data") or {}) if isinstance(data.get("compare"), dict) else {}
    reasons: list[str] = []
    seen: set[str] = set()

    for source in (data.get("rejected_reasons"), compare_data.get("rejected_reasons")):
        if isinstance(source, dict):
            for values in source.values():
                if isinstance(values, list):
                    for item in values:
                        _append_reason(reasons, seen, item)
                else:
                    _append_reason(reasons, seen, values)
        elif isinstance(source, list):
            for item in source:
                _append_reason(reasons, seen, item)

    ranking = data.get("ranking") or compare_data.get("ranking") or []
    if isinstance(ranking, list):
        for item in ranking:
            if not isinstance(item, dict) or item.get("decision") not in {"rejected", "winner"}:
                continue
            for reason in item.get("rejected_reasons") or []:
                _append_reason(reasons, seen, reason)
            if item.get("decision") == "rejected":
                _append_reason(reasons, seen, item.get("failure_reason"))

    promotion = data.get("promotion") or {}
    if isinstance(promotion, dict):
        for reason in promotion.get("gate_reasons") or []:
            _append_reason(reasons, seen, reason)

    return reasons[:limit]


def _collect_process_reasons(payload: dict[str, Any], *, limit: int = 12) -> list[str]:
    data = payload.get("data") or {}
    reasons: list[str] = []
    seen: set[str] = set()
    promotion = data.get("promotion") or {}
    if isinstance(promotion, dict):
        for reason in promotion.get("gate_reasons") or []:
            _append_process_reason(reasons, seen, reason)
        _append_process_reason(reasons, seen, promotion.get("reason"))
    return reasons[:limit]


def _collect_loop_process_reasons(rounds: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    reasons: list[str] = []
    seen: set[str] = set()
    for item in rounds:
        for reason in item.get("process_reasons") or []:
            _append_process_reason(reasons, seen, reason)
    return reasons[:limit]


def _collect_repair_guidance(payload: dict[str, Any], *, limit: int = 12) -> list[str]:
    data = payload.get("data") or {}
    guidance: list[str] = []
    seen: set[str] = set()

    for source in (data.get("agent_repair_guidance"), data.get("repair_guidance")):
        if isinstance(source, list):
            for item in source:
                _append_reason(guidance, seen, item)
        else:
            _append_reason(guidance, seen, source)

    validation = data.get("agent_response_validation")
    if isinstance(validation, dict):
        for item in validation.get("repair_guidance") or []:
            _append_reason(guidance, seen, item)

    return guidance[:limit]


def _agent_artifacts_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    artifacts: dict[str, Any] = {}
    for key in (
        "agent_handoff",
        "agent_prompt",
        "agent_feedback",
        "agent_response_template",
        "agent_response",
        "agent_response_validation",
    ):
        artifacts[key] = data.get(key) or files.get(key)
    return artifacts


def _context_health_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data") or {}
    health = data.get("context_health")
    return health if isinstance(health, dict) else None


def _agent_next_action_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data") or {}
    action = data.get("agent_next_action")
    return action if isinstance(action, dict) else None


def _agent_submission_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data") or {}
    submission = data.get("agent_submission")
    return submission if isinstance(submission, dict) else None


def _loop_context_health_summary(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    quality_order = {"unknown": 0, "limited": 1, "partial": 2, "ready": 3}
    health_by_round: list[dict[str, Any]] = []
    warning_sources: list[str] = []
    missing_inputs: list[str] = []
    seen_warnings: set[str] = set()
    seen_missing: set[str] = set()
    ready_count = 0
    partial_count = 0
    limited_count = 0
    market_data_ready_count = 0
    worst_quality = "unknown"

    for item in rounds:
        health = item.get("context_health") if isinstance(item.get("context_health"), dict) else {}
        quality = str(health.get("quality") or "unknown")
        if quality not in quality_order:
            quality = "unknown"
        if worst_quality == "unknown" or quality_order[quality] < quality_order[worst_quality]:
            worst_quality = quality
        if quality == "ready":
            ready_count += 1
        elif quality == "partial":
            partial_count += 1
        elif quality == "limited":
            limited_count += 1
        if bool(health.get("market_data_ready")):
            market_data_ready_count += 1

        for source in health.get("warning_sources") or []:
            value = str(source).strip()
            if value and value not in seen_warnings:
                seen_warnings.add(value)
                warning_sources.append(value)
        for missing in health.get("missing_inputs") or []:
            value = str(missing).strip()
            if value and value not in seen_missing:
                seen_missing.add(value)
                missing_inputs.append(value)

        health_by_round.append(
            {
                "round": item.get("round"),
                "run_id": item.get("run_id"),
                "quality": quality,
                "market_data_ready": bool(health.get("market_data_ready")),
                "quote_available": bool(health.get("quote_available")),
                "indicator_available": bool(health.get("indicator_available")),
                "news_requested": bool(health.get("news_requested")),
                "news_available": bool(health.get("news_available")),
                "missing_inputs": health.get("missing_inputs") or [],
                "warning_sources": health.get("warning_sources") or [],
            }
        )

    return {
        "scope": "loop_single_symbol_context_health",
        "round_count": len(rounds),
        "rounds_with_context_health": sum(1 for item in rounds if isinstance(item.get("context_health"), dict)),
        "ready_count": ready_count,
        "partial_count": partial_count,
        "limited_count": limited_count,
        "market_data_ready_count": market_data_ready_count,
        "all_market_data_ready": bool(rounds) and market_data_ready_count == len(rounds),
        "worst_quality": worst_quality if rounds else "unknown",
        "missing_inputs": missing_inputs,
        "warning_sources": warning_sources,
        "health_by_round": health_by_round,
        "note": "Read-only rollup of per-round context health; not a promotion gate or trading signal.",
    }


def _final_agent_handoff(rounds: list[dict[str, Any]]) -> str | None:
    for item in reversed(rounds):
        artifacts = item.get("agent_artifacts") if isinstance(item.get("agent_artifacts"), dict) else {}
        handoff = artifacts.get("agent_handoff") or item.get("agent_handoff")
        if handoff:
            return str(handoff)
    return None


def _final_agent_next_action(rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reversed(rounds):
        action = item.get("agent_next_action")
        if isinstance(action, dict):
            return action
    return None


def _final_agent_submission(rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reversed(rounds):
        submission = item.get("agent_submission")
        if isinstance(submission, dict):
            return submission
    return None


def _final_agent_round(rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reversed(rounds):
        artifacts = item.get("agent_artifacts") if isinstance(item.get("agent_artifacts"), dict) else {}
        if artifacts or item.get("agent_handoff") or isinstance(item.get("agent_submission"), dict):
            return item
    return rounds[-1] if rounds else None


def _loop_agent_continuation(*, goal: dict[str, Any], rounds: list[dict[str, Any]], decision: dict[str, Any]) -> dict[str, Any]:
    final_round = _final_agent_round(rounds)
    artifacts = final_round.get("agent_artifacts") if isinstance(final_round, dict) else {}
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    submission = decision.get("final_agent_submission")
    if not isinstance(submission, dict):
        submission = _final_agent_submission(rounds) or {}
    submission_context = submission.get("submission_context") if isinstance(submission.get("submission_context"), dict) else {}

    read_order = ["agent_prompt", "agent_feedback", "agent_response_template"]
    if artifacts.get("agent_response"):
        read_order.append("agent_response")
    if artifacts.get("agent_response_validation"):
        read_order.append("agent_response_validation")

    return {
        "artifact_type": "loop_agent_continuation",
        "available": bool(final_round),
        "purpose": "Read-only continuation packet for the next external Agent candidate-generation turn.",
        "loop_id": goal.get("loop_id"),
        "mode": (goal.get("request") or {}).get("mode"),
        "source_round": final_round.get("round") if isinstance(final_round, dict) else None,
        "source_run_id": final_round.get("run_id") if isinstance(final_round, dict) else None,
        "agent_handoff": decision.get("final_agent_handoff") or _final_agent_handoff(rounds),
        "read_order": read_order if final_round else [],
        "artifacts": {
            key: artifacts.get(key)
            for key in (
                "agent_prompt",
                "agent_feedback",
                "agent_response_template",
                "agent_response",
                "agent_response_validation",
            )
            if artifacts.get(key)
        },
        "agent_next_action": decision.get("final_agent_next_action") or _final_agent_next_action(rounds) or {},
        "submission_context": submission_context,
        "candidate_payload": submission.get("candidate_payload"),
        "feedback": {
            "final_rejected_reasons": decision.get("final_rejected_reasons") or [],
            "final_repair_guidance": decision.get("final_repair_guidance") or [],
            "final_process_reasons": decision.get("final_process_reasons") or [],
            "loop_risk_summary": decision.get("loop_risk_summary") or _loop_risk_summary(rounds),
            "loop_context_health_summary": decision.get("loop_context_health_summary") or _loop_context_health_summary(rounds),
        },
        "do_not_execute_submission_command": True,
        "submission_command_included": False,
        "paper_allowed": False,
        "current_change_allowed": False,
        "live_trading_allowed": False,
        "watchlist_expansion_allowed": False,
        "note": "Use this packet to prepare the next Agent response; do not execute submission command templates from loop artifacts.",
    }


def _loop_agent_generator_task(
    *,
    goal: dict[str, Any],
    decision: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    continuation = decision.get("loop_agent_continuation")
    if not isinstance(continuation, dict):
        continuation = {}
    submission_context = continuation.get("submission_context") if isinstance(continuation.get("submission_context"), dict) else {}
    artifacts = continuation.get("artifacts") if isinstance(continuation.get("artifacts"), dict) else {}
    output_path = artifact_dir / "agent_generator_output.json"
    candidate_count = int(submission_context.get("candidate_count") or (goal.get("request") or {}).get("candidate_count") or 2)
    candidate_count = max(2, min(5, candidate_count))

    return {
        "artifact_type": "loop_agent_generator_task",
        "available": bool(continuation.get("available")),
        "purpose": "Task packet for an external Agent/LLM to generate candidate JSON for the file adapter.",
        "loop_id": goal.get("loop_id"),
        "source_round": continuation.get("source_round"),
        "source_run_id": continuation.get("source_run_id"),
        "source_continuation": "loop_agent_continuation",
        "read_order": continuation.get("read_order") or [],
        "input_artifacts": {
            key: artifacts.get(key)
            for key in (
                "agent_prompt",
                "agent_feedback",
                "agent_response_template",
                "agent_response",
                "agent_response_validation",
            )
            if artifacts.get(key)
        },
        "feedback": continuation.get("feedback") or {},
        "agent_next_action": continuation.get("agent_next_action") or {},
        "submission_context": submission_context,
        "output_contract": {
            "format": "json",
            "output_path": _display_path(output_path),
            "candidate_count": candidate_count,
            "required_top_level": ["candidates"],
            "candidate_required_fields": ["id", "hypothesis", "changes", "content"],
            "content": "StrategyConfig-compatible YAML string for the target symbol.",
            "note": "Write this JSON file only; the trade-agent will read it later with --agent-generator-mode=file.",
        },
        "file_adapter": {
            "agent_generator_mode": "file",
            "agent_generator_output": _display_path(output_path),
            "allowed_verification_modes": ["suggest", "dry_run"],
            "paper_allowed": False,
            "current_change_allowed": False,
        },
        "safety_constraints": [
            "Generate candidate JSON only.",
            "Do not execute submission command templates.",
            "Do not activate paper or live trading.",
            "Do not change config/strategies/current.",
            "Do not expand the user-provided watchlist.",
            "Use news only as read-only context when present.",
        ],
        "external_agent_required": True,
        "external_model_called": False,
        "command_executed": False,
        "paper_allowed": False,
        "current_change_allowed": False,
        "live_trading_allowed": False,
        "watchlist_expansion_allowed": False,
        "note": "This artifact is a handoff task. It does not call an Agent/LLM and does not validate or execute the output.",
    }


def _loop_agent_handoffs(*, goal: dict[str, Any], rounds: list[dict[str, Any]], decision: dict[str, Any]) -> dict[str, Any]:
    handoff_rounds: list[dict[str, Any]] = []
    for item in rounds:
        artifacts = item.get("agent_artifacts") if isinstance(item.get("agent_artifacts"), dict) else {}
        handoff_rounds.append(
            {
                "round": item.get("round"),
                "ok": item.get("ok"),
                "exit_code": item.get("exit_code"),
                "run_id": item.get("run_id"),
                "artifact_dir": item.get("artifact_dir"),
                "agent_handoff": artifacts.get("agent_handoff") or item.get("agent_handoff"),
                "agent_prompt": artifacts.get("agent_prompt"),
                "agent_feedback": artifacts.get("agent_feedback"),
                "agent_response_template": artifacts.get("agent_response_template"),
                "agent_response": artifacts.get("agent_response"),
                "agent_response_validation": artifacts.get("agent_response_validation"),
                "repair_guidance": item.get("repair_guidance") or [],
                "rejected_reasons": item.get("rejected_reasons") or [],
                "process_reasons": item.get("process_reasons") or [],
                "context_health": item.get("context_health") or {},
                "agent_next_action": item.get("agent_next_action") or {},
                "agent_submission": item.get("agent_submission") or {},
            }
        )
    return {
        "artifact_type": "loop_agent_handoffs",
        "purpose": "Index of per-round Agent handoff artifacts for bounded loop automation. Read-only; not a promotion gate.",
        "loop_id": goal.get("loop_id"),
        "mode": (goal.get("request") or {}).get("mode"),
        "round_count": len(rounds),
        "handoff_count": sum(1 for item in handoff_rounds if item.get("agent_handoff")),
        "final_agent_handoff": decision.get("final_agent_handoff") or _final_agent_handoff(rounds),
        "final_agent_next_action": decision.get("final_agent_next_action") or _final_agent_next_action(rounds),
        "final_agent_submission": decision.get("final_agent_submission") or _final_agent_submission(rounds),
        "loop_agent_continuation": decision.get("loop_agent_continuation")
        or _loop_agent_continuation(goal=goal, rounds=rounds, decision=decision),
        "loop_agent_generator_task": decision.get("loop_agent_generator_task"),
        "final_process_reasons": decision.get("final_process_reasons") or _collect_loop_process_reasons(rounds),
        "loop_context_health_summary": decision.get("loop_context_health_summary") or _loop_context_health_summary(rounds),
        "rounds": handoff_rounds,
        "safety_constraints": [
            "Use handoffs only to guide candidate generation and repair.",
            "Do not activate paper or live trading from this index.",
            "Do not change config/strategies/current from this index.",
            "Do not expand the user-provided watchlist.",
        ],
    }


def _extract_paper_report(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data") or {}
    report = data.get("paper_report")
    if isinstance(report, dict):
        return report
    context_report = ((data.get("context") or {}).get("paper_report") if isinstance(data.get("context"), dict) else None)
    return context_report if isinstance(context_report, dict) else None


def _paper_report_brief(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {"available": False}
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    if isinstance(data.get("data"), dict):
        data = data["data"]
    positions = data.get("positions") if isinstance(data.get("positions"), list) else []
    orders = data.get("recent_orders") if isinstance(data.get("recent_orders"), list) else []
    rejects = data.get("recent_rejects") if isinstance(data.get("recent_rejects"), list) else []
    return {
        "available": bool(report.get("ok")) or bool(data),
        "ok": report.get("ok"),
        "pnl": data.get("pnl"),
        "pnl_pct": data.get("pnl_pct"),
        "positions_count": len(positions),
        "recent_orders_count": len(orders),
        "recent_rejects_count": len(rejects),
    }


def _risk_summary_brief(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {"available": False}
    return {
        "available": True,
        "scope": summary.get("scope"),
        "risk_level": summary.get("risk_level"),
        "risk_flags": summary.get("risk_flags") or [],
        "candidate_count": summary.get("candidate_count"),
        "eligible_count": summary.get("eligible_count"),
        "rejected_count": summary.get("rejected_count"),
        "failed_count": summary.get("failed_count"),
        "max_exposure_pct": summary.get("max_exposure_pct"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "min_return_pct": summary.get("min_return_pct"),
        "max_signals_total": summary.get("max_signals_total"),
    }


def _metric_optional(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _extract_portfolio_risk_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return None

    direct = data.get("portfolio_risk_summary")
    if isinstance(direct, dict):
        return direct

    compare = data.get("compare")
    if isinstance(compare, dict):
        compare_data = compare.get("data")
        if isinstance(compare_data, dict) and isinstance(compare_data.get("portfolio_risk_summary"), dict):
            return compare_data["portfolio_risk_summary"]
    return None


def _loop_risk_summary(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    risk_order = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
    summaries: list[tuple[int, dict[str, Any]]] = []
    for item in rounds:
        summary = item.get("portfolio_risk_summary")
        if isinstance(summary, dict):
            summaries.append((int(item.get("round") or len(summaries) + 1), summary))

    def sum_metric(key: str) -> int:
        total = 0
        for _, summary in summaries:
            value = _metric_optional(summary.get(key))
            if value is not None:
                total += int(value)
        return total

    def metric_values(key: str) -> list[float]:
        values: list[float] = []
        for _, summary in summaries:
            value = _metric_optional(summary.get(key))
            if value is not None:
                values.append(value)
        return values

    risk_flags: list[str] = []
    seen_flags: set[str] = set()
    risk_by_round: list[dict[str, Any]] = []
    highest_level = "unknown"
    for round_index, summary in summaries:
        level = str(summary.get("risk_level") or "unknown")
        if level not in risk_order:
            level = "unknown"
        if risk_order[level] > risk_order[highest_level]:
            highest_level = level

        flags = [str(flag) for flag in summary.get("risk_flags") or [] if str(flag).strip()]
        for flag in flags:
            if flag not in seen_flags:
                seen_flags.add(flag)
                risk_flags.append(flag)

        risk_by_round.append(
            {
                "round": round_index,
                "risk_level": level,
                "risk_flags": flags,
                "candidate_count": int(_metric_optional(summary.get("candidate_count")) or 0),
                "eligible_count": int(_metric_optional(summary.get("eligible_count")) or 0),
                "rejected_count": int(_metric_optional(summary.get("rejected_count")) or 0),
                "failed_count": int(_metric_optional(summary.get("failed_count")) or 0),
            }
        )

    if highest_level == "unknown" and risk_flags:
        highest_level = "medium"

    exposures = metric_values("max_exposure_pct")
    drawdowns = metric_values("max_drawdown_pct")
    returns = metric_values("min_return_pct")
    signals = metric_values("max_signals_total")
    return {
        "scope": "loop_single_symbol_multi_round",
        "risk_level": highest_level if summaries else "unknown",
        "risk_flags": risk_flags,
        "round_count": len(rounds),
        "rounds_with_risk_summary": len(summaries),
        "candidate_count": sum_metric("candidate_count"),
        "eligible_count": sum_metric("eligible_count"),
        "rejected_count": sum_metric("rejected_count"),
        "failed_count": sum_metric("failed_count"),
        "max_exposure_pct": round(max(exposures), 6) if exposures else None,
        "max_drawdown_pct": round(max(drawdowns), 6) if drawdowns else None,
        "min_return_pct": round(min(returns), 6) if returns else None,
        "max_signals_total": int(max(signals)) if signals else None,
        "risk_by_round": risk_by_round,
        "note": "Aggregates per-round single-symbol candidate-set summaries; not a cross-symbol portfolio model.",
    }


def _round_summary(round_index: int, exit_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    promotion = data.get("promotion") or {}
    paper_report = _extract_paper_report(payload)
    portfolio_risk_summary = _extract_portfolio_risk_summary(payload)
    agent_artifacts = _agent_artifacts_from_payload(payload)
    context_health = _context_health_from_payload(payload)
    agent_next_action = _agent_next_action_from_payload(payload)
    agent_submission = _agent_submission_from_payload(payload)
    return {
        "round": round_index,
        "ok": bool(payload.get("ok")) and exit_code == 0,
        "exit_code": exit_code,
        "run_id": data.get("run_id"),
        "artifact_dir": data.get("artifact_dir"),
        "agent_handoff": agent_artifacts.get("agent_handoff"),
        "agent_artifacts": agent_artifacts,
        "winner": data.get("winner"),
        "rejected_reasons": _collect_rejected_reasons(payload),
        "process_reasons": _collect_process_reasons(payload),
        "context_health": context_health,
        "agent_next_action": agent_next_action,
        "agent_submission": agent_submission,
        "repair_guidance": _collect_repair_guidance(payload),
        "promotion": {
            "eligible": promotion.get("eligible") if isinstance(promotion, dict) else None,
            "activated": promotion.get("activated") if isinstance(promotion, dict) else None,
            "gate_passed": promotion.get("gate_passed") if isinstance(promotion, dict) else None,
            "reason": promotion.get("reason") if isinstance(promotion, dict) else None,
        },
        "current_changed": data.get("current_changed"),
        "paper_report": _paper_report_brief(paper_report),
        "portfolio_risk_summary": portfolio_risk_summary,
        "current_before": data.get("current_before"),
        "current_after": data.get("current_after"),
        "next_step": data.get("next_step"),
        "error": payload.get("error"),
    }


def _finalize_artifacts(
    *,
    artifact_dir: Path,
    goal: dict[str, Any],
    rounds: list[dict[str, Any]],
    decision: dict[str, Any],
) -> dict[str, Any]:
    _write_json(artifact_dir / "goal.json", goal)
    _write_json(artifact_dir / "rounds.json", {"rounds": rounds})
    _write_json(artifact_dir / "decision.json", decision)
    _write_json(artifact_dir / "agent_handoffs.json", _loop_agent_handoffs(goal=goal, rounds=rounds, decision=decision))
    _write_json(
        artifact_dir / "agent_generator_task.json",
        decision.get("loop_agent_generator_task")
        or _loop_agent_generator_task(goal=goal, decision=decision, artifact_dir=artifact_dir),
    )
    _write_json(artifact_dir / "loop.json", {"goal": goal, "rounds": rounds, "decision": decision})
    return {
        "artifact_dir": _display_path(artifact_dir),
        "files": {
            "goal": _display_path(artifact_dir / "goal.json"),
            "rounds": _display_path(artifact_dir / "rounds.json"),
            "decision": _display_path(artifact_dir / "decision.json"),
            "agent_handoffs": _display_path(artifact_dir / "agent_handoffs.json"),
            "agent_generator_task": _display_path(artifact_dir / "agent_generator_task.json"),
            "loop": _display_path(artifact_dir / "loop.json"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded multi-round E4/E5 strategy loops.")
    parser.add_argument("--strategy", default="current/fast_1m.yaml", help="Baseline strategy")
    parser.add_argument("--symbol", required=True, help="Target symbol, e.g. BTC_USDT")
    parser.add_argument("--watchlist", default="", help="Comma-separated watchlist; passed to each evolve round")
    parser.add_argument("--market", default="", help="Optional market hint")
    parser.add_argument("--days", type=int, default=7, help="Backtest lookback days per round")
    parser.add_argument("--rounds", type=int, default=3, help="Number of bounded loop rounds, 1-10")
    parser.add_argument("--timeframe", default="", help="Optional timeframe override")
    parser.add_argument("--provider", default="", help="Optional provider override")
    parser.add_argument("--min-strength", type=int, default=50, help="Min signal strength")
    parser.add_argument("--initial-equity", type=float, default=None, help="Optional paper initial equity")
    parser.add_argument("--notional", type=float, default=None, help="Optional paper notional")
    parser.add_argument("--candidate-count", type=int, default=2, help="Candidate count per round, clamped to 2-3")
    parser.add_argument("--previous-rejected-reasons", default="", help="Seed rejected reasons for round 1")
    parser.add_argument("--previous-repair-guidance", default="", help="Seed repair guidance for round 1")
    parser.add_argument(
        "--previous-rehearsal-feedback",
        default="",
        help="Optional rehearsal_feedback.json path or JSON object; read-only seed for round 1 previous_* inputs",
    )
    parser.add_argument(
        "--previous-rehearsal-chain-summary",
        default="",
        help="Optional rehearsal_chain_summary.json path or JSON object; resolves next_loop_feedback as round 1 seed",
    )
    parser.add_argument("--include-news", action="store_true", help="Pass optional read-only news context to each evolve round")
    parser.add_argument("--news-limit", type=int, default=5, help="Max news articles per round when --include-news is used")
    parser.add_argument("--news-since-minutes", type=int, default=240, help="News lookback minutes when --include-news is used")
    parser.add_argument("--run-id", default="", help="Optional loop run id")
    parser.add_argument("--mode", choices=["suggest", "dry_run", "paper"], default="dry_run", help="Loop mode")
    parser.add_argument("--keep-candidates", action="store_true", help="Keep generated root candidate YAML files")
    parser.add_argument("--cleanup-old-candidates", action="store_true", help="Ask each round to clean old root candidate YAML files")
    parser.add_argument("--keep-last-runs", type=int, default=10, help="Passed through to evolve cleanup")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-backtest timeout seconds")
    parser.add_argument("--round-timeout", type=float, default=300.0, help="Subprocess timeout per evolve round")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue after a failed round; default fail-closed")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    response = _base_response()
    try:
        loop_id = _safe_run_id(args.run_id, args.symbol)
    except ValueError as e:
        response["error"] = _error_payload("invalid_run_id", str(e))
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1

    artifact_dir = ARTIFACTS_ROOT / loop_id
    rounds_requested = int(args.rounds)
    candidate_count = max(2, min(3, int(args.candidate_count)))
    response["request"] = {
        "strategy": args.strategy,
        "symbol": args.symbol,
        "watchlist": args.watchlist or None,
        "market": args.market or None,
        "days": args.days,
        "rounds": rounds_requested,
        "timeframe": args.timeframe or None,
        "provider": args.provider or None,
        "min_strength": args.min_strength,
        "initial_equity": args.initial_equity,
        "notional": args.notional,
        "candidate_count": candidate_count,
        "previous_rejected_reasons": args.previous_rejected_reasons,
        "previous_repair_guidance": args.previous_repair_guidance,
        "previous_rehearsal_feedback": args.previous_rehearsal_feedback or None,
        "previous_rehearsal_chain_summary": args.previous_rehearsal_chain_summary or None,
        "previous_rehearsal_feedback_inputs": {"loaded": False},
        "include_news": bool(args.include_news),
        "news_limit": args.news_limit,
        "news_since_minutes": args.news_since_minutes,
        "run_id": loop_id,
        "mode": args.mode,
        "keep_candidates": bool(args.keep_candidates) or not args.cleanup_old_candidates,
        "cleanup_old_candidates": bool(args.cleanup_old_candidates),
        "keep_last_runs": args.keep_last_runs,
        "timeout": args.timeout,
        "round_timeout": args.round_timeout,
        "continue_on_failure": bool(args.continue_on_failure),
    }
    goal = {
        "loop_id": loop_id,
        "created_at": response["ts"],
        "request": response["request"],
        "objective": "bounded multi-round strategy generation and verification loop",
        "non_goals": ["no live trading", "no full-market stock selection", "news is not required"],
    }

    validation_error: dict[str, Any] | None = None
    if not EVOLVE_SCRIPT.is_file():
        validation_error = _error_payload("not_found", "tradecat_strategy_evolve.py not found")
    elif args.days <= 0:
        validation_error = _error_payload("invalid_arguments", "--days must be > 0")
    elif rounds_requested <= 0 or rounds_requested > 10:
        validation_error = _error_payload("invalid_arguments", "--rounds must be between 1 and 10")
    elif args.keep_candidates and args.cleanup_old_candidates:
        validation_error = _error_payload("invalid_arguments", "--keep-candidates and --cleanup-old-candidates are mutually exclusive")
    elif args.keep_last_runs < 0:
        validation_error = _error_payload("invalid_arguments", "--keep-last-runs must be >= 0")
    elif args.timeout <= 0 or args.round_timeout <= 0:
        validation_error = _error_payload("invalid_arguments", "timeouts must be > 0")
    elif args.news_limit <= 0:
        validation_error = _error_payload("invalid_arguments", "--news-limit must be > 0")
    elif args.news_since_minutes <= 0:
        validation_error = _error_payload("invalid_arguments", "--news-since-minutes must be > 0")

    previous_rehearsal_feedback: dict[str, Any] | None = None
    if validation_error is None and (args.previous_rehearsal_feedback or args.previous_rehearsal_chain_summary):
        try:
            previous_rehearsal_feedback = _load_previous_feedback_seed(
                feedback_raw=args.previous_rehearsal_feedback,
                chain_summary_raw=args.previous_rehearsal_chain_summary,
            )
        except (json.JSONDecodeError, ValueError) as e:
            validation_error = _error_payload("invalid_previous_rehearsal_feedback", str(e))
    response["request"]["previous_rehearsal_feedback_inputs"] = _previous_rehearsal_feedback_summary(
        previous_rehearsal_feedback
    )

    if validation_error is not None:
        decision = {"ok": False, "error": validation_error, "rounds_completed": 0}
        loop_agent_continuation = _loop_agent_continuation(goal=goal, rounds=[], decision=decision)
        decision["loop_agent_continuation"] = loop_agent_continuation
        loop_agent_generator_task = _loop_agent_generator_task(goal=goal, decision=decision, artifact_dir=artifact_dir)
        decision["loop_agent_generator_task"] = loop_agent_generator_task
        artifact = _finalize_artifacts(artifact_dir=artifact_dir, goal=goal, rounds=[], decision=decision)
        response["data"] = {
            "loop_id": loop_id,
            **artifact,
            "agent_handoffs": artifact["files"]["agent_handoffs"],
            "agent_generator_task": artifact["files"]["agent_generator_task"],
            "final_agent_handoff": None,
            "final_agent_next_action": None,
            "final_agent_submission": None,
            "loop_agent_continuation": loop_agent_continuation,
            "loop_agent_generator_task": loop_agent_generator_task,
            "previous_rehearsal_feedback_inputs": response["request"]["previous_rehearsal_feedback_inputs"],
            "final_process_reasons": [],
            "loop_context_health_summary": _loop_context_health_summary([]),
            "rounds": [],
            "rounds_completed": 0,
        }
        response["error"] = validation_error
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1

    current_before = _current_target()
    previous_rejected_reasons = [item.strip() for item in re.split(r"[,;\n]+", args.previous_rejected_reasons) if item.strip()]
    previous_repair_guidance = [item.strip() for item in re.split(r"[,;\n]+", args.previous_repair_guidance) if item.strip()]
    previous_paper_report: dict[str, Any] | None = None
    previous_risk_summary: dict[str, Any] | None = None
    if previous_rehearsal_feedback:
        _merge_feedback_strings(
            previous_rejected_reasons,
            previous_rehearsal_feedback.get("previous_rejected_reasons") or [],
        )
        _merge_feedback_strings(
            previous_repair_guidance,
            previous_rehearsal_feedback.get("previous_repair_guidance") or [],
        )
        feedback_risk_summary = previous_rehearsal_feedback.get("previous_risk_summary")
        if isinstance(feedback_risk_summary, dict) and feedback_risk_summary:
            previous_risk_summary = feedback_risk_summary
    round_summaries: list[dict[str, Any]] = []
    loop_error: dict[str, Any] | None = None

    for round_index in range(1, rounds_requested + 1):
        round_run_id = f"{loop_id}_r{round_index:02d}"
        exit_code, payload = _run_evolve(
            strategy=args.strategy,
            symbol=args.symbol,
            watchlist=args.watchlist,
            market=args.market,
            days=args.days,
            timeframe=args.timeframe,
            provider=args.provider,
            min_strength=args.min_strength,
            initial_equity=args.initial_equity,
            notional=args.notional,
            candidate_count=candidate_count,
            mode=args.mode,
            run_id=round_run_id,
            previous_rejected_reasons=previous_rejected_reasons,
            previous_paper_report=previous_paper_report,
            previous_risk_summary=previous_risk_summary,
            previous_repair_guidance=previous_repair_guidance,
            include_news=bool(args.include_news),
            news_limit=max(1, min(20, int(args.news_limit))),
            news_since_minutes=max(1, int(args.news_since_minutes)),
            cleanup_old_candidates=bool(args.cleanup_old_candidates),
            keep_candidates=bool(args.keep_candidates),
            keep_last_runs=args.keep_last_runs,
            backtest_timeout=args.timeout,
            round_timeout=args.round_timeout,
        )
        summary = _round_summary(round_index, exit_code, payload)
        summary["input_rejected_reasons"] = previous_rejected_reasons
        summary["input_repair_guidance"] = previous_repair_guidance
        summary["input_paper_report"] = _paper_report_brief(previous_paper_report)
        summary["input_risk_summary"] = _risk_summary_brief(previous_risk_summary)
        round_summaries.append(summary)
        previous_rejected_reasons = summary["rejected_reasons"]
        previous_repair_guidance = summary["repair_guidance"]
        previous_paper_report = _extract_paper_report(payload) or previous_paper_report
        previous_risk_summary = summary.get("portfolio_risk_summary") or previous_risk_summary

        if args.mode == "dry_run" and (summary.get("current_changed") or _current_target() != current_before):
            loop_error = _error_payload(
                "current_changed",
                "dry_run loop changed config/strategies/current; fail closed",
                {
                    "round_index": round_index,
                    "current_before": current_before,
                    "current_after": _current_target(),
                    "round": summary,
                },
            )
            break

        if (exit_code != 0 or not payload.get("ok")) and not args.continue_on_failure:
            loop_error = _error_payload(
                "round_failed",
                f"loop stopped because round {round_index} failed",
                {"round": round_index, "round_error": payload.get("error"), "round_summary": summary},
            )
            break

    current_after = _current_target()
    completed = len(round_summaries)
    all_rounds_ok = all(bool(item.get("ok")) for item in round_summaries)
    loop_risk_summary = _loop_risk_summary(round_summaries)
    loop_context_health_summary = _loop_context_health_summary(round_summaries)
    final_agent_handoff = _final_agent_handoff(round_summaries)
    final_agent_next_action = _final_agent_next_action(round_summaries)
    final_agent_submission = _final_agent_submission(round_summaries)
    final_process_reasons = _collect_loop_process_reasons(round_summaries)
    decision = {
        "ok": loop_error is None and completed == rounds_requested and all_rounds_ok,
        "mode": args.mode,
        "loop_id": loop_id,
        "rounds_requested": rounds_requested,
        "rounds_completed": completed,
        "all_rounds_ok": all_rounds_ok,
        "stopped_early": completed < rounds_requested,
        "final_rejected_reasons": previous_rejected_reasons,
        "final_process_reasons": final_process_reasons,
        "final_repair_guidance": previous_repair_guidance,
        "current_before": current_before,
        "current_after": current_after,
        "current_changed": current_before != current_after,
        "loop_risk_summary": loop_risk_summary,
        "loop_context_health_summary": loop_context_health_summary,
        "final_agent_handoff": final_agent_handoff,
        "final_agent_next_action": final_agent_next_action,
        "final_agent_submission": final_agent_submission,
        "error": loop_error,
        "next_step": (
            "Review loop artifacts and decide whether to run paper mode explicitly."
            if args.mode == "dry_run"
            else "Review paper activation/report artifacts before another loop."
            if args.mode == "paper"
            else "Review suggested candidates before dry_run."
        ),
    }
    loop_agent_continuation = _loop_agent_continuation(goal=goal, rounds=round_summaries, decision=decision)
    decision["loop_agent_continuation"] = loop_agent_continuation
    loop_agent_generator_task = _loop_agent_generator_task(goal=goal, decision=decision, artifact_dir=artifact_dir)
    decision["loop_agent_generator_task"] = loop_agent_generator_task
    artifact = _finalize_artifacts(artifact_dir=artifact_dir, goal=goal, rounds=round_summaries, decision=decision)

    response["ok"] = bool(decision["ok"])
    response["data"] = {
        "mode": args.mode,
        "loop_id": loop_id,
        **artifact,
        "agent_handoffs": artifact["files"]["agent_handoffs"],
        "agent_generator_task": artifact["files"]["agent_generator_task"],
        "final_agent_handoff": final_agent_handoff,
        "final_agent_next_action": final_agent_next_action,
        "final_agent_submission": final_agent_submission,
        "loop_agent_continuation": loop_agent_continuation,
        "loop_agent_generator_task": loop_agent_generator_task,
        "previous_rehearsal_feedback_inputs": response["request"]["previous_rehearsal_feedback_inputs"],
        "rounds_requested": rounds_requested,
        "rounds_completed": completed,
        "rounds": round_summaries,
        "final_rejected_reasons": previous_rejected_reasons,
        "final_process_reasons": final_process_reasons,
        "final_repair_guidance": previous_repair_guidance,
        "loop_risk_summary": loop_risk_summary,
        "loop_context_health_summary": loop_context_health_summary,
        "current_before": current_before,
        "current_after": current_after,
        "current_changed": current_before != current_after,
        "next_step": decision["next_step"],
    }
    response["error"] = loop_error
    json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
