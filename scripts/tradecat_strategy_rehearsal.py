#!/usr/bin/env python3
"""Safe rehearsal for loop task -> file adapter strategy generation.

This script does not call an external LLM. It runs a suggest-mode loop to obtain
agent_generator_task.json, writes a deterministic stub Agent JSON to the task's
output path, then verifies that JSON through tradecat_strategy_evolve.py using
the file adapter in suggest/dry_run mode.
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

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LOOP_SCRIPT = REPO_ROOT / "scripts" / "tradecat_strategy_loop.py"
EVOLVE_SCRIPT = REPO_ROOT / "scripts" / "tradecat_strategy_evolve.py"
STRATEGIES_ROOT = REPO_ROOT / "config" / "strategies"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "strategy-runs"
TOOL_NAME = "tradecat_strategy_rehearsal"


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


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _current_target() -> str | None:
    current = STRATEGIES_ROOT / "current"
    if current.is_symlink() or current.exists():
        return str(current.resolve(strict=False))
    return None


def _safe_run_id(raw: str, symbol: str) -> str:
    value = (raw or "").strip()
    if not value:
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        value = f"rehearsal_{stamp}_{symbol}"
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
    if not value:
        raise ValueError("run id is empty")
    if value in {".", ".."} or ".." in value:
        raise ValueError("run id may not contain '..'")
    if len(value) > 96:
        raise ValueError("run id is too long")
    return value


def _run_json(cmd: list[str], *, timeout: float) -> tuple[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 1, {"ok": False, "error": _error_payload("timeout", f"timeout after {timeout}s")}
    except Exception as e:  # noqa: BLE001
        return 1, {"ok": False, "error": _error_payload("spawn_failed", str(e))}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.returncode or 1, {
            "ok": False,
            "error": _error_payload(
                "invalid_json",
                "child command did not return JSON",
                {"stderr_tail": result.stderr.splitlines()[-10:], "stdout_tail": result.stdout.splitlines()[-10:]},
            ),
        }
    return result.returncode, payload


def _resolve_output_path(raw: str) -> Path:
    value = (raw or "").strip()
    if not value:
        raise ValueError("agent generator task missing output_path")
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _watchlist_items(raw: Any, *, label: str) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        values: list[Any] = raw.split(",")
    elif isinstance(raw, list):
        values = raw
    else:
        raise ValueError(f"{label} must be a list or comma-separated string")

    items: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            raise ValueError(f"{label} must contain only strings")
        value = item.strip()
        if value and value not in seen:
            seen.add(value)
            items.append(value)
    return items


def _validate_task_boundaries(*, args: argparse.Namespace, task: dict[str, Any]) -> None:
    context = task.get("submission_context") if isinstance(task.get("submission_context"), dict) else {}
    requested_watchlist = _watchlist_items(args.watchlist, label="request.watchlist")
    allowed_symbols = set(requested_watchlist or [args.symbol])
    if args.symbol not in allowed_symbols:
        raise ValueError("requested symbol must be included in the user-provided watchlist")

    task_symbol = str(context.get("symbol") or args.symbol).strip()
    if task_symbol and task_symbol != args.symbol:
        raise ValueError("agent generator task symbol must match the requested symbol")

    task_watchlist = _watchlist_items(context.get("watchlist"), label="submission_context.watchlist")
    expanded = [symbol for symbol in task_watchlist if symbol not in allowed_symbols]
    if expanded:
        raise ValueError(
            "agent generator task expanded watchlist outside user request: "
            + ", ".join(expanded[:5])
        )


def _candidate_yaml(*, symbol: str, index: int, min_strength: int, timeframe: str | None, market: str | None) -> str:
    strength = max(30, min(90, min_strength + (index - 1) * 2))
    cooldown = 600 + (index - 1) * 300
    buy_threshold = max(10, min(45, 34 - (index - 1) * 2))
    sell_threshold = max(55, min(90, 70 + (index - 1) * 2))
    data = {
        "name": f"Rehearsal Agent Candidate {index}",
        "market": market or "crypto_spot",
        "symbols": [symbol],
        "timeframe": timeframe or "5m",
        "indicators": [{"name": "rsi", "params": {"period": 14}}],
        "thresholds": {"min_strength": strength},
        "rules": [
            {
                "name": f"Rehearsal RSI pullback {index}",
                "direction": "BUY",
                "strength": strength,
                "cooldown": cooldown,
                "condition": {"type": "indicator", "field": "rsi", "op": "lt", "threshold": buy_threshold},
            },
            {
                "name": f"Rehearsal RSI exit {index}",
                "direction": "SELL",
                "strength": strength,
                "cooldown": cooldown,
                "condition": {"type": "indicator", "field": "rsi", "op": "gt", "threshold": sell_threshold},
            },
        ],
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _stub_agent_output(task: dict[str, Any]) -> dict[str, Any]:
    context = task.get("submission_context") if isinstance(task.get("submission_context"), dict) else {}
    contract = task.get("output_contract") if isinstance(task.get("output_contract"), dict) else {}
    symbol = str(context.get("symbol") or "BTC_USDT")
    candidate_count = max(2, min(5, int(contract.get("candidate_count") or context.get("candidate_count") or 2)))
    min_strength = int(context.get("min_strength") or 50)
    timeframe = str(context.get("timeframe") or "") or None
    market = str(context.get("market") or "") or None
    feedback = task.get("feedback") if isinstance(task.get("feedback"), dict) else {}

    candidates = []
    for index in range(1, candidate_count + 1):
        candidates.append(
            {
                "id": f"rehearsal_{index:02d}",
                "hypothesis": f"Rehearsal candidate {index} generated from loop feedback.",
                "changes": [
                    "Use task submission_context without expanding watchlist.",
                    "Keep RSI thresholds and cooldowns within static sanity bounds.",
                    f"Reference final_process_reasons={len(feedback.get('final_process_reasons') or [])}.",
                ],
                "content": _candidate_yaml(
                    symbol=symbol,
                    index=index,
                    min_strength=min_strength,
                    timeframe=timeframe,
                    market=market,
                ),
            }
        )
    return {"candidates": candidates}


def _dedupe_strings(items: list[Any]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _collect_rejected_reasons(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rejected = data.get("rejected_reasons")
    reasons: list[Any] = []
    if isinstance(rejected, dict):
        for value in rejected.values():
            if isinstance(value, list):
                reasons.extend(value)
            elif value:
                reasons.append(value)
    elif isinstance(rejected, list):
        reasons.extend(rejected)
    elif rejected:
        reasons.append(rejected)
    return _dedupe_strings(reasons)


def _collect_process_reasons(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    promotion = data.get("promotion") if isinstance(data.get("promotion"), dict) else {}
    reasons: list[Any] = []
    reasons.extend(promotion.get("gate_reasons") or [])
    if promotion.get("reason"):
        reasons.append(promotion.get("reason"))
    if data.get("next_step"):
        reasons.append(data.get("next_step"))
    if payload.get("error"):
        error = payload.get("error")
        if isinstance(error, dict):
            reasons.append(error.get("message") or error.get("code"))
        else:
            reasons.append(error)
    return _dedupe_strings(reasons)


def _extract_risk_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    summary = data.get("portfolio_risk_summary")
    if isinstance(summary, dict):
        return summary
    compare = data.get("compare")
    compare_data = compare.get("data") if isinstance(compare, dict) and isinstance(compare.get("data"), dict) else {}
    summary = compare_data.get("portfolio_risk_summary") if isinstance(compare_data, dict) else None
    return summary if isinstance(summary, dict) else None


def _extract_repair_guidance(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    guidance: list[Any] = []
    value = data.get("agent_repair_guidance") or data.get("repair_guidance")
    if isinstance(value, list):
        guidance.extend(value)
    validation = data.get("agent_response_validation")
    if isinstance(validation, dict):
        guidance.extend(validation.get("repair_guidance") or [])
    return _dedupe_strings(guidance)


def _artifact_fields(data: dict[str, Any]) -> dict[str, Any]:
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    fields = {}
    for key in (
        "agent_generator",
        "agent_response",
        "agent_response_validation",
        "agent_handoff",
        "agent_prompt",
        "agent_feedback",
        "agent_response_template",
    ):
        fields[key] = data.get(key) or files.get(key)
    return fields


def _rehearsal_feedback(
    *,
    run_id: str,
    loop_payload: dict[str, Any],
    verify_payload: dict[str, Any],
    task: dict[str, Any],
    generator_output_path: Path,
    verify_mode: str,
    current_changed: bool,
) -> dict[str, Any]:
    verify_data = verify_payload.get("data") if isinstance(verify_payload.get("data"), dict) else {}
    loop_data = loop_payload.get("data") if isinstance(loop_payload.get("data"), dict) else {}
    risk_summary = _extract_risk_summary(verify_payload)
    rejected_reasons = _collect_rejected_reasons(verify_payload)
    repair_guidance = _extract_repair_guidance(verify_payload)
    process_reasons = _collect_process_reasons(verify_payload)
    context_health = verify_data.get("context_health") if isinstance(verify_data.get("context_health"), dict) else {}
    response_validation = verify_data.get("agent_response_validation")
    validation_artifact = response_validation if isinstance(response_validation, str) else None

    return {
        "artifact_type": "rehearsal_feedback",
        "available": bool(verify_payload.get("ok")) and not current_changed,
        "run_id": run_id,
        "verify_mode": verify_mode,
        "loop_run_id": loop_data.get("loop_id"),
        "verify_run_id": verify_data.get("run_id"),
        "agent_generator_output": _display_path(generator_output_path),
        "source_task": "loop_agent_generator_task",
        "source_task_artifact": loop_data.get("agent_generator_task"),
        "verify_artifacts": _artifact_fields(verify_data),
        "next_loop_inputs": {
            "previous_rejected_reasons": rejected_reasons,
            "previous_repair_guidance": repair_guidance,
            "previous_risk_summary": risk_summary or {},
            "previous_context_health": context_health,
            "previous_agent_response_validation": validation_artifact,
            "previous_agent_generator_output": _display_path(generator_output_path),
        },
        "agent_next_action": verify_data.get("agent_next_action") if isinstance(verify_data.get("agent_next_action"), dict) else {},
        "agent_submission": verify_data.get("agent_submission") if isinstance(verify_data.get("agent_submission"), dict) else {},
        "process_reasons": process_reasons,
        "candidate_count": len(verify_data.get("candidates") or []) if isinstance(verify_data.get("candidates"), list) else 0,
        "promotion": verify_data.get("promotion") if isinstance(verify_data.get("promotion"), dict) else {},
        "current_changed": current_changed,
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
        "note": "Read-only feedback for the next loop or external Agent turn; not a promotion gate or trading signal.",
    }


def _loop_args(
    args: argparse.Namespace,
    *,
    loop_run_id: str,
    previous_rehearsal_feedback: str = "",
    previous_rehearsal_chain_summary: str = "",
) -> list[str]:
    cmd = [
        sys.executable,
        str(LOOP_SCRIPT),
        "--strategy",
        args.strategy,
        "--symbol",
        args.symbol,
        "--days",
        str(args.days),
        "--rounds",
        str(args.rounds),
        "--candidate-count",
        str(args.candidate_count),
        "--mode",
        "suggest",
        "--run-id",
        loop_run_id,
        "--timeout",
        str(args.timeout),
        "--round-timeout",
        str(args.round_timeout),
    ]
    if args.watchlist:
        cmd += ["--watchlist", args.watchlist]
    if args.market:
        cmd += ["--market", args.market]
    if args.timeframe:
        cmd += ["--timeframe", args.timeframe]
    if args.provider:
        cmd += ["--provider", args.provider]
    cmd += ["--min-strength", str(args.min_strength)]
    if args.include_news:
        cmd += ["--include-news", "--news-limit", str(args.news_limit), "--news-since-minutes", str(args.news_since_minutes)]
    if previous_rehearsal_feedback:
        cmd += ["--previous-rehearsal-feedback", previous_rehearsal_feedback]
    if previous_rehearsal_chain_summary:
        cmd += ["--previous-rehearsal-chain-summary", previous_rehearsal_chain_summary]
    return cmd


def _verify_args(
    *,
    args: argparse.Namespace,
    task: dict[str, Any],
    generator_output_path: Path,
    verify_run_id: str,
) -> list[str]:
    context = task.get("submission_context") if isinstance(task.get("submission_context"), dict) else {}
    watchlist = context.get("watchlist")
    watchlist_arg = ",".join(str(item) for item in watchlist) if isinstance(watchlist, list) else str(watchlist or args.watchlist)
    cmd = [
        sys.executable,
        str(EVOLVE_SCRIPT),
        "--strategy",
        str(context.get("strategy") or args.strategy),
        "--symbol",
        str(context.get("symbol") or args.symbol),
        "--days",
        str(int(context.get("days") or args.days)),
        "--candidate-count",
        str(int(context.get("candidate_count") or args.candidate_count)),
        "--min-strength",
        str(int(context.get("min_strength") or args.min_strength)),
        "--mode",
        args.verify_mode,
        "--run-id",
        verify_run_id,
        "--timeout",
        str(float(context.get("timeout") or args.timeout)),
        "--agent-generator-mode",
        "file",
        "--agent-generator-output",
        str(generator_output_path),
    ]
    if watchlist_arg:
        cmd += ["--watchlist", watchlist_arg]
    for flag, key, fallback in (
        ("--market", "market", args.market),
        ("--timeframe", "timeframe", args.timeframe),
        ("--provider", "provider", args.provider),
    ):
        value = str(context.get(key) or fallback or "").strip()
        if value:
            cmd += [flag, value]
    if bool(context.get("include_news")) or args.include_news:
        cmd += [
            "--include-news",
            "--news-limit",
            str(int(context.get("news_limit") or args.news_limit)),
            "--news-since-minutes",
            str(int(context.get("news_since_minutes") or args.news_since_minutes)),
        ]
    return cmd


def _cycle_id(run_id: str, *, cycle_index: int, cycles: int) -> str:
    if cycles == 1:
        return run_id
    return f"{run_id}_c{cycle_index:02d}"


def _cycle_feedback_path(artifact_dir: Path, *, cycle_index: int, cycles: int) -> Path:
    if cycles == 1:
        return artifact_dir / "rehearsal_feedback.json"
    return artifact_dir / f"cycle_{cycle_index:02d}_rehearsal_feedback.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _latest_next_loop_input_summary(feedback: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(feedback, dict):
        return {"available": False}
    inputs = feedback.get("next_loop_inputs") if isinstance(feedback.get("next_loop_inputs"), dict) else {}
    context_health = inputs.get("previous_context_health") if isinstance(inputs.get("previous_context_health"), dict) else {}
    risk_summary = inputs.get("previous_risk_summary") if isinstance(inputs.get("previous_risk_summary"), dict) else {}
    return {
        "available": True,
        "previous_rejected_reason_count": len(inputs.get("previous_rejected_reasons") or []),
        "previous_repair_guidance_count": len(inputs.get("previous_repair_guidance") or []),
        "previous_risk_summary_available": bool(risk_summary),
        "previous_risk_level": risk_summary.get("risk_level"),
        "previous_context_health_quality": context_health.get("quality"),
        "previous_market_data_ready": context_health.get("market_data_ready"),
        "previous_agent_response_validation": inputs.get("previous_agent_response_validation"),
        "previous_agent_generator_output": inputs.get("previous_agent_generator_output"),
    }


def _cycle_summary(cycle: dict[str, Any]) -> dict[str, Any]:
    feedback = cycle.get("rehearsal_feedback") if isinstance(cycle.get("rehearsal_feedback"), dict) else {}
    next_inputs = _latest_next_loop_input_summary(feedback)
    promotion = cycle.get("promotion") if isinstance(cycle.get("promotion"), dict) else {}
    return {
        "cycle": cycle.get("cycle"),
        "ok": bool(cycle.get("ok")),
        "cycle_run_id": cycle.get("cycle_run_id"),
        "loop_run_id": cycle.get("loop_run_id"),
        "verify_run_id": cycle.get("verify_run_id"),
        "previous_rehearsal_feedback": cycle.get("previous_rehearsal_feedback"),
        "previous_rehearsal_chain_summary": cycle.get("previous_rehearsal_chain_summary"),
        "rehearsal_feedback": (cycle.get("files") or {}).get("rehearsal_feedback") if isinstance(cycle.get("files"), dict) else None,
        "agent_generator_output": cycle.get("agent_generator_output"),
        "verify_mode": cycle.get("verify_mode"),
        "loop_exit_code": cycle.get("loop_exit_code"),
        "verify_exit_code": cycle.get("verify_exit_code"),
        "candidate_count": cycle.get("agent_generator_output_candidate_count"),
        "promotion_activated": bool(promotion.get("activated")),
        "current_changed": bool(cycle.get("current_changed")),
        "next_loop_inputs": next_inputs,
        "error": cycle.get("error"),
    }


def _request_params(request: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key in keys:
        value = request.get(key)
        if value is not None and value != "":
            params[key] = value
    return params


def _context_param(context: dict[str, Any], request: dict[str, Any], key: str) -> Any:
    value = context.get(key)
    if value is not None and value != "":
        return value
    return request.get(key)


def _watchlist_param(raw: Any) -> str | None:
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
        return ",".join(values) if values else None
    if isinstance(raw, str):
        value = raw.strip()
        return value or None
    return None


def _latest_agent_generator_request(*, request: dict[str, Any], cycles: list[dict[str, Any]]) -> dict[str, Any]:
    latest_cycle: dict[str, Any] = {}
    latest_task: dict[str, Any] = {}
    for cycle in reversed(cycles):
        task = cycle.get("loop_agent_generator_task") if isinstance(cycle.get("loop_agent_generator_task"), dict) else {}
        if cycle.get("ok") and task:
            latest_cycle = cycle
            latest_task = task
            break
    if not latest_task:
        return {
            "available": False,
            "reason": "no successful loop_agent_generator_task available",
            "command_included": False,
        }

    context = latest_task.get("submission_context") if isinstance(latest_task.get("submission_context"), dict) else {}
    output_contract = latest_task.get("output_contract") if isinstance(latest_task.get("output_contract"), dict) else {}
    output_path = output_contract.get("output_path")
    candidate_count = output_contract.get("candidate_count") or _context_param(context, request, "candidate_count") or 2
    input_artifacts = latest_task.get("input_artifacts") if isinstance(latest_task.get("input_artifacts"), dict) else {}
    watchlist = _watchlist_param(_context_param(context, request, "watchlist"))

    verify_params: dict[str, Any] = {}
    for key in ("strategy", "symbol", "market", "days", "timeframe", "provider", "min_strength", "candidate_count"):
        value = _context_param(context, request, key)
        if value is not None and value != "":
            verify_params[key] = value
    if watchlist:
        verify_params["watchlist"] = watchlist
    if bool(_context_param(context, request, "include_news")):
        verify_params["include_news"] = True
        verify_params["news_limit"] = _context_param(context, request, "news_limit")
        verify_params["news_since_minutes"] = _context_param(context, request, "news_since_minutes")
    verify_params["mode"] = "suggest"
    verify_params["agent_generator_mode"] = "file"
    verify_params["agent_generator_output"] = output_path

    return {
        "available": True,
        "tool": "external_agent_generate_candidates",
        "purpose": "Ask an external Agent/LLM to generate candidate JSON, then verify that JSON through the file adapter.",
        "params": {
            "agent_generator_task": ((latest_cycle.get("loop") or {}).get("data") or {}).get("agent_generator_task")
            if isinstance(latest_cycle.get("loop"), dict) and isinstance((latest_cycle.get("loop") or {}).get("data"), dict)
            else None,
            "read_order": latest_task.get("read_order") or [],
            "input_artifacts": input_artifacts,
            "output_path": output_path,
            "candidate_count": candidate_count,
            "required_top_level": output_contract.get("required_top_level") or ["candidates"],
            "candidate_required_fields": output_contract.get("candidate_required_fields")
            or ["id", "hypothesis", "changes", "content"],
            "content": output_contract.get("content"),
            "submission_context": {
                key: value
                for key, value in {
                    "strategy": _context_param(context, request, "strategy"),
                    "symbol": _context_param(context, request, "symbol"),
                    "watchlist": watchlist,
                    "market": _context_param(context, request, "market"),
                    "days": _context_param(context, request, "days"),
                    "timeframe": _context_param(context, request, "timeframe"),
                    "provider": _context_param(context, request, "provider"),
                    "min_strength": _context_param(context, request, "min_strength"),
                    "candidate_count": candidate_count,
                    "include_news": bool(_context_param(context, request, "include_news")),
                    "news_limit": _context_param(context, request, "news_limit"),
                    "news_since_minutes": _context_param(context, request, "news_since_minutes"),
                }.items()
                if value is not None and value != ""
            },
        },
        "verify_request": {
            "tool": "trade_strategy_evolve",
            "params": verify_params,
            "purpose": "Verify the generated JSON in suggest mode through the file adapter.",
            "command_included": False,
        },
        "safety": {
            "external_model_called": False,
            "external_generator_command_executed": False,
            "submission_command_executed": False,
            "paper_allowed": False,
            "live_trading_allowed": False,
            "current_change_allowed": False,
            "watchlist_expansion_allowed": False,
        },
        "command_included": False,
        "note": "This is a parameter handoff only. Generate the JSON file, then run the verify_request through the tool layer; do not execute shell command templates.",
    }


def _rehearsal_chain_summary(
    *,
    run_id: str,
    request: dict[str, Any],
    artifact_dir: Path,
    cycles: list[dict[str, Any]],
    cycle_feedback_chain: list[dict[str, Any]],
    latest_feedback: dict[str, Any] | None,
    latest_feedback_path: Path | None,
    response_ok: bool,
    current_before: str | None,
    current_after: str | None,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    cycle_summaries = [_cycle_summary(cycle) for cycle in cycles]
    latest_cycle = cycle_summaries[-1] if cycle_summaries else {}
    latest_action = latest_feedback.get("agent_next_action") if isinstance(latest_feedback, dict) and isinstance(latest_feedback.get("agent_next_action"), dict) else {}
    latest_promotion = latest_feedback.get("promotion") if isinstance(latest_feedback, dict) and isinstance(latest_feedback.get("promotion"), dict) else {}
    next_feedback = _display_path(latest_feedback_path) if latest_feedback_path else None
    summary_path = _display_path(artifact_dir / "rehearsal_chain_summary.json")
    rehearsal_params = _request_params(
        request,
        (
            "strategy",
            "symbol",
            "watchlist",
            "market",
            "days",
            "rounds",
            "cycles",
            "timeframe",
            "provider",
            "min_strength",
            "candidate_count",
            "verify_mode",
            "include_news",
            "news_limit",
            "news_since_minutes",
        ),
    )
    rehearsal_params["previous_rehearsal_chain_summary"] = summary_path
    loop_params = _request_params(
        request,
        (
            "strategy",
            "symbol",
            "watchlist",
            "market",
            "days",
            "rounds",
            "timeframe",
            "provider",
            "min_strength",
            "candidate_count",
            "include_news",
            "news_limit",
            "news_since_minutes",
        ),
    )
    loop_params["mode"] = "suggest"
    loop_params["previous_rehearsal_chain_summary"] = summary_path
    return {
        "artifact_type": "rehearsal_chain_summary",
        "available": bool(cycles),
        "ok": response_ok,
        "run_id": run_id,
        "created_at": _utc_now_iso(),
        "purpose": "Compact read-only summary of a rehearsal feedback chain for the next automation step.",
        "cycles_requested": request.get("cycles"),
        "cycles_completed": len(cycles),
        "latest_cycle": latest_cycle.get("cycle"),
        "latest_rehearsal_feedback": next_feedback,
        "next_loop_feedback": next_feedback,
        "cycle_feedback_chain": cycle_feedback_chain,
        "cycle_summaries": cycle_summaries,
        "latest_next_loop_inputs": _latest_next_loop_input_summary(latest_feedback),
        "next_agent_generator_request": _latest_agent_generator_request(request=request, cycles=cycles),
        "next_rehearsal_request": {
            "tool": "trade_strategy_rehearsal",
            "params": rehearsal_params,
            "purpose": "Continue the safe rehearsal feedback chain using this summary as the next seed.",
            "command_included": False,
        },
        "next_loop_request": {
            "tool": "trade_strategy_loop",
            "params": loop_params,
            "purpose": "Run a safe suggest loop using this summary as read-only feedback seed.",
            "command_included": False,
        },
        "latest_agent_next_action": {
            "action": latest_action.get("action"),
            "readiness": latest_action.get("readiness"),
            "candidate_style": latest_action.get("candidate_style"),
            "blocked": bool(latest_action.get("blocked")),
            "reasons": latest_action.get("reasons") or [],
        },
        "promotion": {
            "activated": bool(latest_promotion.get("activated")),
            "eligible": latest_promotion.get("eligible"),
            "gate_passed": latest_promotion.get("gate_passed"),
            "reason": latest_promotion.get("reason"),
        },
        "current_before": current_before,
        "current_after": current_after,
        "current_changed": current_before != current_after,
        "error": error,
        "files": {
            "rehearsal": _display_path(artifact_dir / "rehearsal.json"),
            "rehearsal_feedback": next_feedback,
            "rehearsal_chain_summary": summary_path,
        },
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
        "note": "Use next_loop_feedback as a read-only input to --previous-rehearsal-feedback; do not execute command templates from full artifacts.",
    }


def _run_cycle(
    *,
    args: argparse.Namespace,
    run_id: str,
    cycles: int,
    cycle_index: int,
    artifact_dir: Path,
    current_before: str | None,
    previous_rehearsal_feedback: str,
    previous_rehearsal_chain_summary: str = "",
) -> tuple[dict[str, Any], dict[str, Any] | None, Path | None, dict[str, Any] | None]:
    cycle_run_id = _cycle_id(run_id, cycle_index=cycle_index, cycles=cycles)
    loop_run_id = f"{cycle_run_id}_loop"
    verify_run_id = f"{cycle_run_id}_verify"

    loop_code, loop_payload = _run_json(
        _loop_args(
            args,
            loop_run_id=loop_run_id,
            previous_rehearsal_feedback=previous_rehearsal_feedback,
            previous_rehearsal_chain_summary=previous_rehearsal_chain_summary,
        ),
        timeout=args.round_timeout * args.rounds + 60,
    )
    loop_data = loop_payload.get("data") if isinstance(loop_payload.get("data"), dict) else {}
    task = loop_data.get("loop_agent_generator_task") if isinstance(loop_data.get("loop_agent_generator_task"), dict) else {}
    if loop_code != 0 or not loop_payload.get("ok") or not task:
        current_after = _current_target()
        cycle = {
            "cycle": cycle_index,
            "cycle_run_id": cycle_run_id,
            "loop_run_id": loop_run_id,
            "verify_run_id": verify_run_id,
            "previous_rehearsal_feedback": previous_rehearsal_feedback or None,
            "previous_rehearsal_chain_summary": previous_rehearsal_chain_summary or None,
            "ok": False,
            "loop_exit_code": loop_code,
            "verify_exit_code": None,
            "loop": loop_payload,
            "verify": None,
            "current_before": current_before,
            "current_after": current_after,
            "current_changed": current_before != current_after,
            "error": _error_payload(
                "loop_rehearsal_failed",
                "suggest loop did not produce an Agent generator task",
                {"loop_exit_code": loop_code, "loop_error": loop_payload.get("error")},
            ),
        }
        return cycle, None, None, cycle["error"]

    try:
        _validate_task_boundaries(args=args, task=task)
        output_path = _resolve_output_path(
            ((task.get("output_contract") or {}).get("output_path") if isinstance(task.get("output_contract"), dict) else "")
        )
    except ValueError as e:
        current_after = _current_target()
        error = _error_payload("invalid_agent_generator_task", str(e))
        cycle = {
            "cycle": cycle_index,
            "cycle_run_id": cycle_run_id,
            "loop_run_id": loop_run_id,
            "verify_run_id": verify_run_id,
            "previous_rehearsal_feedback": previous_rehearsal_feedback or None,
            "previous_rehearsal_chain_summary": previous_rehearsal_chain_summary or None,
            "ok": False,
            "loop_exit_code": loop_code,
            "verify_exit_code": None,
            "loop": loop_payload,
            "verify": None,
            "current_before": current_before,
            "current_after": current_after,
            "current_changed": current_before != current_after,
            "error": error,
        }
        return cycle, None, None, error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stub_output = _stub_agent_output(task)
    _write_json(output_path, stub_output)

    verify_code, verify_payload = _run_json(
        _verify_args(args=args, task=task, generator_output_path=output_path, verify_run_id=verify_run_id),
        timeout=args.round_timeout + 30,
    )
    current_after = _current_target()
    current_changed = current_before != current_after
    ok = bool(loop_payload.get("ok")) and bool(verify_payload.get("ok")) and verify_code == 0 and not current_changed
    rehearsal_feedback = _rehearsal_feedback(
        run_id=cycle_run_id,
        loop_payload=loop_payload,
        verify_payload=verify_payload,
        task=task,
        generator_output_path=output_path,
        verify_mode=args.verify_mode,
        current_changed=current_changed,
    )
    rehearsal_feedback["chain_run_id"] = run_id
    rehearsal_feedback["cycle"] = cycle_index
    rehearsal_feedback["cycles_requested"] = cycles
    rehearsal_feedback["previous_rehearsal_feedback"] = previous_rehearsal_feedback or None
    rehearsal_feedback["previous_rehearsal_chain_summary"] = previous_rehearsal_chain_summary or None
    rehearsal_feedback_path = _cycle_feedback_path(artifact_dir, cycle_index=cycle_index, cycles=cycles)
    _write_json(rehearsal_feedback_path, rehearsal_feedback)

    cycle_error = None
    if not ok:
        cycle_error = _error_payload(
            "rehearsal_failed",
            "loop-to-file-adapter rehearsal failed or changed current",
            {"verify_error": verify_payload.get("error"), "current_changed": current_changed},
        )
    cycle = {
        "cycle": cycle_index,
        "cycle_run_id": cycle_run_id,
        "loop_run_id": loop_run_id,
        "verify_run_id": verify_run_id,
        "previous_rehearsal_feedback": previous_rehearsal_feedback or None,
        "previous_rehearsal_chain_summary": previous_rehearsal_chain_summary or None,
        "ok": ok,
        "files": {
            "rehearsal_feedback": _display_path(rehearsal_feedback_path),
            "agent_generator_output": _display_path(output_path),
        },
        "loop_agent_generator_task": task,
        "rehearsal_feedback": rehearsal_feedback,
        "agent_generator_output": _display_path(output_path),
        "agent_generator_output_candidate_count": len(stub_output["candidates"]),
        "verify_mode": args.verify_mode,
        "loop_exit_code": loop_code,
        "verify_exit_code": verify_code,
        "loop": loop_payload,
        "verify": verify_payload,
        "current_before": current_before,
        "current_after": current_after,
        "current_changed": current_changed,
        "promotion": ((verify_payload.get("data") or {}).get("promotion") if isinstance(verify_payload.get("data"), dict) else None),
        "error": cycle_error,
    }
    return cycle, rehearsal_feedback, rehearsal_feedback_path, cycle_error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe E5 Agent generator rehearsal.")
    parser.add_argument("--strategy", default="current/fast_1m.yaml", help="Baseline strategy")
    parser.add_argument("--symbol", required=True, help="Target symbol, e.g. BTC_USDT")
    parser.add_argument("--watchlist", default="", help="Comma-separated watchlist")
    parser.add_argument("--market", default="", help="Optional market hint")
    parser.add_argument("--days", type=int, default=1, help="Loop/evolve lookback days")
    parser.add_argument("--rounds", type=int, default=2, help="Suggest loop rounds before rehearsal, 1-5")
    parser.add_argument("--cycles", type=int, default=1, help="Feedback rehearsal cycles, 1-5; each cycle feeds feedback into the next")
    parser.add_argument("--timeframe", default="", help="Optional timeframe override")
    parser.add_argument("--provider", default="", help="Optional provider override")
    parser.add_argument("--min-strength", type=int, default=50, help="Min signal strength")
    parser.add_argument("--candidate-count", type=int, default=2, help="Candidate count, clamped to 2-5 for output")
    parser.add_argument("--verify-mode", choices=["suggest", "dry_run"], default="suggest", help="File adapter verification mode")
    parser.add_argument("--include-news", action="store_true", help="Pass optional read-only news context")
    parser.add_argument("--news-limit", type=int, default=5, help="Max news articles when include_news is used")
    parser.add_argument("--news-since-minutes", type=int, default=240, help="News lookback minutes when include_news is used")
    parser.add_argument(
        "--previous-rehearsal-feedback",
        default="",
        help="Optional rehearsal_feedback.json path or JSON object used as the first cycle seed",
    )
    parser.add_argument(
        "--previous-rehearsal-chain-summary",
        default="",
        help="Optional rehearsal_chain_summary.json path or JSON object used as the first cycle seed",
    )
    parser.add_argument("--run-id", default="", help="Optional rehearsal run id")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-backtest timeout seconds")
    parser.add_argument("--round-timeout", type=float, default=300.0, help="Subprocess timeout per loop/evolve run")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    response = _base_response()
    try:
        run_id = _safe_run_id(args.run_id, args.symbol)
    except ValueError as e:
        response["error"] = _error_payload("invalid_run_id", str(e))
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.days <= 0 or args.rounds <= 0 or args.rounds > 5 or args.cycles <= 0 or args.cycles > 5:
        response["error"] = _error_payload(
            "invalid_arguments",
            "--days must be > 0, --rounds must be between 1 and 5, and --cycles must be between 1 and 5",
        )
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.timeout <= 0 or args.round_timeout <= 0:
        response["error"] = _error_payload("invalid_arguments", "timeouts must be > 0")
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.previous_rehearsal_feedback and args.previous_rehearsal_chain_summary:
        response["error"] = _error_payload(
            "invalid_arguments",
            "--previous-rehearsal-feedback and --previous-rehearsal-chain-summary are mutually exclusive",
        )
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1

    artifact_dir = ARTIFACTS_ROOT / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    loop_run_id = f"{run_id}_loop"
    verify_run_id = f"{run_id}_verify"
    current_before = _current_target()
    response["request"] = {
        "strategy": args.strategy,
        "symbol": args.symbol,
        "watchlist": args.watchlist or None,
        "market": args.market or None,
        "days": args.days,
        "rounds": args.rounds,
        "cycles": args.cycles,
        "timeframe": args.timeframe or None,
        "provider": args.provider or None,
        "min_strength": args.min_strength,
        "candidate_count": args.candidate_count,
        "verify_mode": args.verify_mode,
        "run_id": run_id,
        "loop_run_id": loop_run_id,
        "verify_run_id": verify_run_id,
        "previous_rehearsal_feedback": args.previous_rehearsal_feedback or None,
        "previous_rehearsal_chain_summary": args.previous_rehearsal_chain_summary or None,
        "include_news": bool(args.include_news),
        "news_limit": args.news_limit,
        "news_since_minutes": args.news_since_minutes,
    }

    cycles: list[dict[str, Any]] = []
    cycle_feedback_chain: list[dict[str, Any]] = []
    previous_feedback = args.previous_rehearsal_feedback
    latest_feedback: dict[str, Any] | None = None
    latest_feedback_path: Path | None = None
    latest_cycle: dict[str, Any] | None = None
    loop_error: dict[str, Any] | None = None
    previous_summary = args.previous_rehearsal_chain_summary
    for cycle_index in range(1, args.cycles + 1):
        cycle, feedback, feedback_path, cycle_error = _run_cycle(
            args=args,
            run_id=run_id,
            cycles=args.cycles,
            cycle_index=cycle_index,
            artifact_dir=artifact_dir,
            current_before=current_before,
            previous_rehearsal_feedback=previous_feedback,
            previous_rehearsal_chain_summary=previous_summary,
        )
        cycles.append(cycle)
        latest_cycle = cycle
        if feedback is not None and feedback_path is not None:
            latest_feedback = feedback
            latest_feedback_path = feedback_path
            cycle_feedback_chain.append(
                {
                    "cycle": cycle_index,
                    "rehearsal_feedback": _display_path(feedback_path),
                    "previous_rehearsal_feedback": cycle.get("previous_rehearsal_feedback"),
                    "previous_rehearsal_chain_summary": cycle.get("previous_rehearsal_chain_summary"),
                    "available": bool(feedback.get("available")),
                    "rejected_reason_count": len((feedback.get("next_loop_inputs") or {}).get("previous_rejected_reasons") or []),
                    "repair_guidance_count": len((feedback.get("next_loop_inputs") or {}).get("previous_repair_guidance") or []),
                    "risk_summary_available": bool((feedback.get("next_loop_inputs") or {}).get("previous_risk_summary")),
                }
            )
            previous_feedback = _display_path(feedback_path)
            previous_summary = ""
        if cycle_error is not None:
            loop_error = cycle_error
            break

    if latest_feedback is not None and latest_feedback_path is not None and latest_feedback_path.name != "rehearsal_feedback.json":
        _write_json(artifact_dir / "rehearsal_feedback.json", latest_feedback)
        latest_feedback_path = artifact_dir / "rehearsal_feedback.json"

    current_after = _current_target()
    response["ok"] = loop_error is None and len(cycles) == args.cycles and all(bool(item.get("ok")) for item in cycles)
    latest_cycle = latest_cycle or {}
    response_error = None
    if not response["ok"]:
        response_error = loop_error or _error_payload(
            "rehearsal_failed",
            "loop-to-file-adapter rehearsal failed or changed current",
            {"current_changed": current_before != current_after},
        )
    rehearsal_chain_summary = _rehearsal_chain_summary(
        run_id=run_id,
        request=response["request"],
        artifact_dir=artifact_dir,
        cycles=cycles,
        cycle_feedback_chain=cycle_feedback_chain,
        latest_feedback=latest_feedback,
        latest_feedback_path=latest_feedback_path,
        response_ok=bool(response["ok"]),
        current_before=current_before,
        current_after=current_after,
        error=response_error,
    )
    chain_summary_path = artifact_dir / "rehearsal_chain_summary.json"
    _write_json(chain_summary_path, rehearsal_chain_summary)
    response["data"] = {
        "artifact_dir": _display_path(artifact_dir),
        "files": {
            "rehearsal": _display_path(artifact_dir / "rehearsal.json"),
            "rehearsal_feedback": _display_path(latest_feedback_path) if latest_feedback_path else None,
            "rehearsal_chain_summary": _display_path(chain_summary_path),
            "agent_generator_output": latest_cycle.get("agent_generator_output"),
            "cycle_feedbacks": [item["rehearsal_feedback"] for item in cycle_feedback_chain],
        },
        "cycles_requested": args.cycles,
        "cycles_completed": len(cycles),
        "cycle_feedback_chain": cycle_feedback_chain,
        "rehearsal_chain_summary": rehearsal_chain_summary,
        "cycles": cycles,
        "loop_run_id": latest_cycle.get("loop_run_id") or loop_run_id,
        "verify_run_id": latest_cycle.get("verify_run_id") or verify_run_id,
        "loop_agent_generator_task": latest_cycle.get("loop_agent_generator_task"),
        "rehearsal_feedback": latest_feedback,
        "agent_generator_output": latest_cycle.get("agent_generator_output"),
        "agent_generator_output_candidate_count": latest_cycle.get("agent_generator_output_candidate_count"),
        "verify_mode": args.verify_mode,
        "loop_exit_code": latest_cycle.get("loop_exit_code"),
        "verify_exit_code": latest_cycle.get("verify_exit_code"),
        "loop": latest_cycle.get("loop"),
        "verify": latest_cycle.get("verify"),
        "current_before": current_before,
        "current_after": current_after,
        "current_changed": current_before != current_after,
        "promotion": latest_cycle.get("promotion"),
        "safety": {
            "external_model_called": False,
            "external_generator_command_executed": False,
            "internal_validation_commands_executed": True,
            "paper_allowed": False,
            "live_trading_allowed": False,
            "current_change_allowed": False,
            "watchlist_expansion_allowed": False,
            "submission_command_executed": False,
        },
    }
    if not response["ok"]:
        response["error"] = response_error

    _write_json(artifact_dir / "rehearsal.json", response)
    json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
