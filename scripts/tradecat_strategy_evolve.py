#!/usr/bin/env python3
"""E4 MVP strategy loop controller.

Default mode is dry_run: generate candidate YAML strategies, validate/write them
through tradecat_strategy_manage.py, backtest/compare through
tradecat_strategy_compare.py, and recommend a winner without activating current.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
STRATEGIES_ROOT = REPO_ROOT / "config" / "strategies"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "strategy-runs"
TOOL_NAME = "tradecat_strategy_evolve"
MANAGE_SCRIPT = REPO_ROOT / "scripts" / "tradecat_strategy_manage.py"
COMPARE_SCRIPT = REPO_ROOT / "scripts" / "tradecat_strategy_compare.py"
QUOTES_SCRIPT = REPO_ROOT / "scripts" / "tradecat_get_quotes.py"
INDICATORS_SCRIPT = REPO_ROOT / "scripts" / "tradecat_get_indicators.py"
PAPER_REPORT_SCRIPT = REPO_ROOT / "scripts" / "tradecat_agent_paper_report.py"
NEWS_SCRIPT = REPO_ROOT / "scripts" / "tradecat_get_news.py"


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_id(symbol: str) -> str:
    safe_symbol = re.sub(r"[^A-Za-z0-9_]+", "_", symbol.strip().upper()).strip("_") or "SYMBOL"
    return f"{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}_{safe_symbol}"


def _safe_run_id(raw: str, symbol: str) -> str:
    value = (raw or "").strip()
    if not value:
        return _run_id(symbol)
    safe = _json_safe_filename(value)
    if safe != value or "/" in value or "\\" in value or ".." in value:
        raise ValueError("run_id may only contain letters, numbers, underscore, dot, and dash")
    return safe


def _error_payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"code": code, "message": message, "details": details}


def _base_response() -> dict:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "ts": _utc_now_iso(),
        "request": {},
        "data": None,
        "error": None,
    }


def _json_safe_filename(raw: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw.strip()).strip("._")
    return safe or "item"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _init_artifact_dir(run_id: str) -> Path:
    safe_run_id = _json_safe_filename(run_id)
    path = ARTIFACTS_ROOT / safe_run_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "candidates").mkdir(parents=True, exist_ok=True)
    return path


def _artifact_rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _write_candidate_artifacts(artifact_dir: Path, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    written: list[dict[str, Any]] = []
    cand_dir = artifact_dir / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        name = _json_safe_filename(candidate["strategy"])
        if not name.endswith((".yaml", ".yml")):
            name = f"{name}.yaml"
        path = cand_dir / name
        path.write_text(candidate["content"], encoding="utf-8")
        written.append(
            {
                "strategy": candidate["strategy"],
                "path": _artifact_rel(path),
                "hypothesis": candidate.get("hypothesis"),
                "changes": candidate.get("changes") or [],
            }
        )
    return written


def _write_text_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_written_candidate_artifacts(artifact_dir: Path, candidate_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    cand_dir = artifact_dir / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    for item in candidate_results:
        strategy = item.get("strategy") or ""
        src = STRATEGIES_ROOT / strategy
        if not src.is_file():
            continue
        dest = cand_dir / _json_safe_filename(src.name)
        shutil.copy2(src, dest)
        copied.append({"strategy": strategy, "path": _artifact_rel(dest)})
    return copied


def _is_agent_candidate(path: Path) -> bool:
    return path.is_file() and path.parent == STRATEGIES_ROOT and path.name.startswith("agent_") and path.suffix in {
        ".yaml",
        ".yml",
    }


def _cleanup_old_candidates(*, keep_last_runs: int) -> dict[str, Any]:
    if keep_last_runs < 0:
        keep_last_runs = 0
    root = STRATEGIES_ROOT.resolve(strict=False)
    groups: dict[str, list[Path]] = {}
    for path in STRATEGIES_ROOT.iterdir():
        resolved = path.resolve(strict=False)
        if resolved.parent != root or not _is_agent_candidate(path):
            continue
        run_key = path.stem.rsplit("_", 1)[0]
        groups.setdefault(run_key, []).append(path)

    ordered_groups = sorted(
        groups.items(),
        key=lambda item: (max(path.stat().st_mtime for path in item[1]), item[0]),
        reverse=True,
    )
    keep_groups = ordered_groups[:keep_last_runs]
    delete_groups = ordered_groups[keep_last_runs:]
    keep = [path for _, paths in keep_groups for path in sorted(paths)]
    delete = [path for _, paths in delete_groups for path in sorted(paths)]
    deleted: list[str] = []
    skipped: list[str] = []
    for path in delete:
        resolved = path.resolve(strict=False)
        if resolved.parent != root or not _is_agent_candidate(path):
            skipped.append(_artifact_rel(path))
            continue
        path.unlink()
        deleted.append(_artifact_rel(path))
    return {
        "enabled": True,
        "keep_last_runs": keep_last_runs,
        "kept_run_count": len(keep_groups),
        "deleted_run_count": len(delete_groups),
        "kept": [_artifact_rel(path) for path in keep],
        "deleted": deleted,
        "skipped": skipped,
    }


def _finalize_artifacts(
    *,
    artifact_dir: Path,
    goal: dict[str, Any],
    context: dict[str, Any] | None = None,
    candidate_results: list[dict[str, Any]] | None = None,
    compare_result: dict[str, Any] | None = None,
    decision: dict[str, Any],
) -> dict[str, Any]:
    _write_json(artifact_dir / "goal.json", goal)
    if context is not None:
        _write_json(artifact_dir / "context.json", context)
    if candidate_results is not None:
        _write_json(artifact_dir / "candidates.json", {"candidates": candidate_results})
        _copy_written_candidate_artifacts(artifact_dir, candidate_results)
    if compare_result is not None:
        _write_json(artifact_dir / "compare.json", compare_result)
    _write_json(artifact_dir / "decision.json", decision)
    return {
        "artifact_dir": _artifact_rel(artifact_dir),
        "files": {
            "goal": _artifact_rel(artifact_dir / "goal.json"),
            "agent_prompt": _artifact_rel(artifact_dir / "agent_prompt.json")
            if (artifact_dir / "agent_prompt.json").exists()
            else None,
            "agent_feedback": _artifact_rel(artifact_dir / "agent_feedback.json")
            if (artifact_dir / "agent_feedback.json").exists()
            else None,
            "agent_handoff": _artifact_rel(artifact_dir / "agent_handoff.json")
            if (artifact_dir / "agent_handoff.json").exists()
            else None,
            "agent_response": _artifact_rel(artifact_dir / "agent_response.json")
            if (artifact_dir / "agent_response.json").exists()
            else None,
            "agent_response_template": _artifact_rel(artifact_dir / "agent_response_template.json")
            if (artifact_dir / "agent_response_template.json").exists()
            else None,
            "agent_response_validation": _artifact_rel(artifact_dir / "agent_response_validation.json")
            if (artifact_dir / "agent_response_validation.json").exists()
            else None,
            "agent_generator": _artifact_rel(artifact_dir / "agent_generator.json")
            if (artifact_dir / "agent_generator.json").exists()
            else None,
            "context": _artifact_rel(artifact_dir / "context.json") if (artifact_dir / "context.json").exists() else None,
            "candidates": _artifact_rel(artifact_dir / "candidates.json") if (artifact_dir / "candidates.json").exists() else None,
            "compare": _artifact_rel(artifact_dir / "compare.json") if (artifact_dir / "compare.json").exists() else None,
            "decision": _artifact_rel(artifact_dir / "decision.json"),
            "candidate_dir": _artifact_rel(artifact_dir / "candidates"),
        },
    }


def _resolve_strategy_path(strategy: str) -> Path:
    raw = (strategy or "").strip()
    if not raw:
        raise FileNotFoundError("Strategy path is empty")
    candidates = [
        STRATEGIES_ROOT / raw,
        STRATEGIES_ROOT / "current" / raw,
    ]
    for candidate in candidates:
        path = candidate.resolve(strict=False)
        if path.is_file() and path.suffix in {".yaml", ".yml"}:
            return path
    raise FileNotFoundError(f"Strategy not found: {strategy}")


def _read_strategy(strategy: str) -> tuple[Path, dict[str, Any]]:
    path = _resolve_strategy_path(strategy)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Strategy YAML is not a mapping: {strategy}")
    return path, data


def _dump_strategy(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _set_symbol(data: dict[str, Any], symbol: str) -> None:
    data["symbols"] = [symbol]


def _candidate_name(symbol: str, run_id: str, index: int) -> str:
    safe_symbol = re.sub(r"[^A-Za-z0-9_]+", "_", symbol.upper()).strip("_") or "SYMBOL"
    return f"agent_{safe_symbol}_{run_id}_{index:02d}.yaml"


def _normalize_changes(value: Any) -> list[str]:
    if isinstance(value, list):
        changes = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        changes = [item.strip(" -\t") for item in value.splitlines() if item.strip(" -\t")]
    else:
        changes = []
    return changes


def _parse_agent_candidate_payload(raw: str) -> Any:
    value = (raw or "").strip()
    if not value:
        return None
    if value.startswith(("{", "[")):
        return json.loads(value)
    path = Path(value)
    if not path.is_file():
        raise ValueError("agent candidates must be a JSON string or an existing JSON file path")
    return json.loads(path.read_text(encoding="utf-8"))


def _agent_candidate_drafts_from_payload(payload: Any) -> list[dict[str, Any]] | None:
    if payload is None:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        items = payload["candidates"]
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise ValueError("agent candidates payload must be a JSON object or array")

    if len(items) < 2 or len(items) > 5:
        raise ValueError("agent candidates must contain 2 to 5 candidates")

    drafts: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"agent candidate #{index} must be an object")
        content = item.get("content") or item.get("yaml") or item.get("strategy_yaml")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"agent candidate #{index} must include strategy YAML content")
        hypothesis = str(item.get("hypothesis") or "").strip()
        if not hypothesis:
            raise ValueError(f"agent candidate #{index} must include hypothesis")
        changes = _normalize_changes(item.get("changes") or item.get("change_summary"))
        if not changes:
            raise ValueError(f"agent candidate #{index} must include non-empty changes")
        drafts.append(
            {
                "index": index,
                "source_id": str(item.get("id") or item.get("name") or f"agent_candidate_{index}").strip(),
                "hypothesis": hypothesis,
                "changes": changes,
                "content": content,
            }
        )
    return drafts


def _load_agent_candidate_drafts(raw: str) -> list[dict[str, Any]] | None:
    return _agent_candidate_drafts_from_payload(_parse_agent_candidate_payload(raw))


def _load_agent_generator_file(raw: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path((raw or "").strip())
    if not path.is_file():
        raise ValueError("--agent-generator-output must be an existing JSON file when --agent-generator-mode=file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    drafts = _agent_candidate_drafts_from_payload(payload)
    if not drafts:
        raise ValueError("agent generator output must contain 2 to 5 candidates")
    return {
        "artifact_type": "agent_generator_adapter",
        "mode": "file",
        "enabled": True,
        "status": "loaded",
        "source": "agent_generator_file",
        "source_path": str(path),
        "candidate_count": len(drafts),
        "candidate_source_ids": [draft["source_id"] for draft in drafts],
        "external_model_called": False,
        "command_executed": False,
        "paper_allowed": False,
        "current_change_allowed": False,
        "live_trading_allowed": False,
        "watchlist_expansion_allowed": False,
        "raw_payload": payload,
        "note": "File adapter only. It reads Agent/LLM-authored JSON and passes it to existing validation; it does not call a model or execute commands.",
    }, drafts


def _agent_drafts_to_candidates(
    *,
    drafts: list[dict[str, Any]],
    symbol: str,
    run_id: str,
    generator_source: str = "agent_draft",
    context: dict[str, Any] | None = None,
    previous_rejected_reasons: list[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    reasons = [str(reason).strip() for reason in previous_rejected_reasons or [] if str(reason).strip()]
    context_notes = _generator_context(
        baseline={},
        context=context,
        previous_rejected_reasons=reasons,
    ).get("notes", [])
    for index, draft in enumerate(drafts, start=1):
        data = yaml.safe_load(draft["content"])
        if not isinstance(data, dict):
            raise ValueError(f"agent candidate #{index} YAML must be a mapping")
        _set_symbol(data, symbol)
        data["name"] = str(data.get("name") or f"Agent draft candidate {index}")
        candidates.append(
            {
                "strategy": _candidate_name(symbol, run_id, index),
                "hypothesis": draft["hypothesis"],
                "changes": draft["changes"],
                "generator_context": {
                    "source": generator_source,
                    "agent_candidate_id": draft["source_id"],
                    "previous_rejected_reasons": reasons,
                    "notes": context_notes,
                    "safety_rewrites": [f"symbols forced to {symbol}"],
                },
                "content": _dump_strategy(data),
            }
        )
    return candidates


def _agent_response_audit(
    *,
    drafts: list[dict[str, Any]],
    candidates: list[dict[str, Any]] | None,
    symbol: str,
    status: str,
    source: str = "agent_draft",
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_by_index = {
        index: candidate
        for index, candidate in enumerate(candidates or [], start=1)
    }
    draft_items: list[dict[str, Any]] = []
    for draft in drafts:
        content = str(draft.get("content") or "")
        candidate = candidate_by_index.get(int(draft.get("index") or len(draft_items) + 1)) or {}
        generator_context = candidate.get("generator_context") if isinstance(candidate, dict) else {}
        draft_items.append(
            {
                "index": draft.get("index"),
                "source_id": draft.get("source_id"),
                "strategy": candidate.get("strategy"),
                "hypothesis": draft.get("hypothesis"),
                "changes": draft.get("changes") or [],
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "content_bytes": len(content.encode("utf-8")),
                "safety_rewrites": (generator_context or {}).get("safety_rewrites") or [],
            }
        )

    return {
        "source": source,
        "status": status,
        "target_symbol": symbol,
        "candidate_count": len(drafts),
        "accepted_count": len(candidates or []),
        "drafts": draft_items,
        "error": error,
        "note": "Audit artifact only. Agent drafts still pass static sanity, write validation, backtest, compare, and promotion gates.",
    }


def _dedupe_strings(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _preflight_repair_guidance(
    *,
    status: str,
    static_sanity: dict[str, Any] | None,
    error: dict[str, Any] | None,
    symbol: str,
) -> dict[str, list[str]]:
    text_parts: list[str] = []
    if isinstance(static_sanity, dict):
        text_parts.extend(str(item) for item in static_sanity.get("errors") or [])
        text_parts.extend(str(item) for item in static_sanity.get("warnings") or [])
    if isinstance(error, dict):
        text_parts.append(str(error.get("code") or ""))
        text_parts.append(str(error.get("message") or ""))
    text = " | ".join(text_parts).lower()
    categories: list[str] = []
    hints: list[str] = []

    if status == "conversion_failed":
        categories.append("yaml_conversion")
        hints.append("Return StrategyConfig-compatible YAML content as a mapping, not prose or partial YAML.")
    if "symbols" in text or "target symbol" in text:
        categories.append("target_symbol")
        hints.append(f"Use only {symbol} in strategy symbols; do not expand or change the watchlist.")
    if "cooldown" in text:
        categories.append("cooldown_bounds")
        hints.append("Set every rule cooldown between 60 and 3600 seconds.")
    if "strength" in text and "min_strength" not in text:
        categories.append("rule_strength_bounds")
        hints.append("Set every rule strength between 30 and 95.")
    if "min_strength" in text:
        categories.append("min_strength_bounds")
        hints.append("Set thresholds.min_strength between 30 and 90.")
    if "rsi threshold" in text or ("threshold" in text and "rsi" in text):
        categories.append("rsi_threshold_bounds")
        hints.append("Keep RSI thresholds between 10 and 90.")
    if "direction" in text and ("buy" in text or "sell" in text):
        categories.append("rule_direction")
        hints.append("Use BUY or SELL for every rule direction.")
    if "at least one rule" in text or "no rules" in text:
        categories.append("missing_rules")
        hints.append("Include at least one valid rule before submitting the candidate.")
    if "single trade direction" in text:
        categories.append("single_direction_warning")
        hints.append("Consider including both BUY and SELL rules unless the hypothesis explicitly tests one-sided behavior.")
    if not categories and status != "ready_for_write":
        categories.append("preflight_failed")
        hints.append("Review the candidate YAML against agent_response_template.json and resubmit a corrected draft.")

    return {"categories": _dedupe_strings(categories), "hints": _dedupe_strings(hints)}


def _agent_response_validation_report(
    *,
    drafts: list[dict[str, Any]],
    candidates: list[dict[str, Any]] | None,
    symbol: str,
    status: str,
    source: str = "agent_draft",
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_by_index = {
        index: candidate
        for index, candidate in enumerate(candidates or [], start=1)
    }
    items: list[dict[str, Any]] = []
    for draft in drafts:
        index = int(draft.get("index") or len(items) + 1)
        candidate = candidate_by_index.get(index) or {}
        generator_context = candidate.get("generator_context") if isinstance(candidate, dict) else {}
        static_sanity = candidate.get("static_sanity") if isinstance(candidate, dict) else None
        static_ok = bool((static_sanity or {}).get("ok")) if isinstance(static_sanity, dict) else None
        yaml_conversion_ok = bool(candidate) if error is None else bool(candidate)
        item_status = "ready_for_write" if static_ok else "static_sanity_failed" if static_ok is False else "conversion_failed"
        guidance = _preflight_repair_guidance(
            status=item_status,
            static_sanity=static_sanity if isinstance(static_sanity, dict) else None,
            error=error,
            symbol=symbol,
        )
        items.append(
            {
                "index": index,
                "source_id": draft.get("source_id"),
                "strategy": candidate.get("strategy"),
                "schema_payload_ok": True,
                "yaml_conversion_ok": yaml_conversion_ok,
                "target_symbol": symbol,
                "static_sanity": static_sanity,
                "safety_rewrites": (generator_context or {}).get("safety_rewrites") or [],
                "status": item_status,
                "failure_categories": guidance["categories"] if item_status != "ready_for_write" else [],
                "repair_hints": guidance["hints"] if item_status != "ready_for_write" else [],
                "review_hints": guidance["hints"] if item_status == "ready_for_write" else [],
            }
        )

    repair_guidance = _dedupe_strings(
        [
            hint
            for item in items
            for hint in item.get("repair_hints", [])
        ]
    )
    if not repair_guidance and any(item.get("review_hints") for item in items):
        repair_guidance = _dedupe_strings(
            [
                hint
                for item in items
                for hint in item.get("review_hints", [])
            ]
        )

    return {
        "source": source,
        "artifact_type": "agent_response_validation",
        "stage": "pre_write_static_sanity",
        "status": status,
        "target_symbol": symbol,
        "candidate_count": len(drafts),
        "ready_count": sum(1 for item in items if item["status"] == "ready_for_write"),
        "failed_count": sum(1 for item in items if item["status"] != "ready_for_write"),
        "repair_guidance": repair_guidance,
        "items": items,
        "error": error,
        "note": "Pre-write report only. Passing this report does not bypass manage validation, backtest, compare, or promotion gates.",
    }


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _static_sanity_check_strategy(data: dict[str, Any], *, symbol: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    symbols = data.get("symbols") if isinstance(data.get("symbols"), list) else []
    rules = data.get("rules") if isinstance(data.get("rules"), list) else []
    thresholds = data.get("thresholds") if isinstance(data.get("thresholds"), dict) else {}

    if symbols != [symbol]:
        errors.append("strategy symbols must match target symbol only")
    if not rules:
        errors.append("strategy must include at least one rule")
    if len(rules) > 24:
        errors.append("strategy has too many rules")

    directions: set[str] = set()
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            errors.append(f"rule #{index} must be a mapping")
            continue
        name = str(rule.get("name") or f"rule #{index}")
        direction = str(rule.get("direction") or "").upper()
        if direction in {"BUY", "SELL"}:
            directions.add(direction)
        else:
            errors.append(f"{name} direction must be BUY or SELL")

        strength = _number(rule.get("strength"))
        if strength is None or strength < 30 or strength > 95:
            errors.append(f"{name} strength must be between 30 and 95")

        cooldown = _number(rule.get("cooldown"))
        if cooldown is None or cooldown < 60 or cooldown > 3600:
            errors.append(f"{name} cooldown must be between 60 and 3600 seconds")

        condition = rule.get("condition") if isinstance(rule.get("condition"), dict) else {}
        cond_type = condition.get("type")
        field = condition.get("field")
        threshold = _number(condition.get("threshold"))
        if cond_type in {"threshold_cross_up", "threshold_cross_down"} and field == "rsi":
            if threshold is None or threshold < 10 or threshold > 90:
                errors.append(f"{name} RSI threshold must be between 10 and 90")
        elif threshold is not None and (threshold < -1_000_000 or threshold > 1_000_000):
            errors.append(f"{name} threshold is outside sanity bounds")

    if not directions.intersection({"BUY", "SELL"}):
        errors.append("strategy must include at least one BUY or SELL rule")
    if len(directions) == 1:
        warnings.append("strategy only has one trade direction")

    min_strength = _number(thresholds.get("min_strength", 50))
    if min_strength is None or min_strength < 30 or min_strength > 90:
        errors.append("thresholds.min_strength must be between 30 and 90")

    max_cooldown = _number(thresholds.get("max_cooldown"))
    if max_cooldown is not None and (max_cooldown < 60 or max_cooldown > 3600):
        errors.append("thresholds.max_cooldown must be between 60 and 3600 when set")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "symbol": symbol,
            "rule_count": len(rules),
            "directions": sorted(directions),
            "min_strength": min_strength,
        },
    }


def _static_sanity_check_candidate(candidate: dict[str, Any], *, symbol: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(candidate.get("content") or "")
    except yaml.YAMLError as e:
        return {"ok": False, "errors": [f"candidate YAML parse failed: {e}"], "warnings": [], "summary": {}}
    if not isinstance(data, dict):
        return {"ok": False, "errors": ["candidate YAML must be a mapping"], "warnings": [], "summary": {}}
    return _static_sanity_check_strategy(data, symbol=symbol)


def _static_sanity_check_candidates(candidates: list[dict[str, Any]], *, symbol: str) -> list[dict[str, Any]]:
    checked: list[dict[str, Any]] = []
    for candidate in candidates:
        result = _static_sanity_check_candidate(candidate, symbol=symbol)
        checked.append({**candidate, "static_sanity": result})
    return checked


def _adjust_thresholds(data: dict[str, Any], delta: int) -> list[str]:
    changes: list[str] = []
    thresholds = dict(data.get("thresholds") or {})
    old_min = int(thresholds.get("min_strength", 50))
    new_min = max(30, min(80, old_min + delta))
    if new_min != old_min:
        thresholds["min_strength"] = new_min
        data["thresholds"] = thresholds
        changes.append(f"min_strength {old_min} -> {new_min}")
    return changes


def _adjust_cooldown(data: dict[str, Any], delta: int) -> list[str]:
    changes: list[str] = []
    for rule in data.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        old = int(rule.get("cooldown", 300))
        new = max(60, min(1800, old + delta))
        if new != old:
            rule["cooldown"] = new
            changes.append(f"{rule.get('name', 'rule')} cooldown {old} -> {new}")
    return changes


def _adjust_rsi_thresholds(
    data: dict[str, Any],
    *,
    tighten: bool | None = None,
    buy_delta: int | None = None,
    sell_delta: int | None = None,
) -> list[str]:
    if tighten is not None:
        buy_delta = -5 if tighten else 3
        sell_delta = 5 if tighten else -3

    changes: list[str] = []
    for rule in data.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        cond = rule.get("condition") or {}
        if not isinstance(cond, dict) or cond.get("field") != "rsi":
            continue
        kind = cond.get("type")
        old = cond.get("threshold")
        if not isinstance(old, (int, float)):
            continue
        new = old
        if kind == "threshold_cross_up" and buy_delta is not None:
            new = max(20, min(45, old + buy_delta))
        elif kind == "threshold_cross_down" and sell_delta is not None:
            new = max(55, min(80, old + sell_delta))
        if new != old:
            cond["threshold"] = new
            rule["condition"] = cond
            changes.append(f"{rule.get('name', 'rule')} RSI threshold {old} -> {new}")
    return changes


def _extract_indicator_context(context: dict[str, Any] | None) -> dict[str, Any]:
    indicators = (((context or {}).get("indicators") or {}).get("data") or {}).get("indicators") or {}
    data = ((context or {}).get("indicators") or {}).get("data") or {}
    quote_items = (((context or {}).get("quotes") or {}).get("data") or [])
    quote = quote_items[0] if quote_items and isinstance(quote_items[0], dict) else {}

    def number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    rsi = number(indicators.get("rsi"))
    ema_fast = number(indicators.get("ema_fast"))
    ema_medium = number(indicators.get("ema_medium"))
    ema_slow = number(indicators.get("ema_slow"))
    macd_hist = number(indicators.get("macd_hist"))
    price = number(quote.get("price")) or number(data.get("close"))

    if rsi is None:
        rsi_zone = "unknown"
    elif rsi >= 65:
        rsi_zone = "overbought"
    elif rsi <= 35:
        rsi_zone = "oversold"
    else:
        rsi_zone = "neutral"

    if ema_fast is None or ema_slow is None:
        trend = "unknown"
    elif ema_fast > ema_slow and (macd_hist is None or macd_hist >= 0):
        trend = "bullish"
    elif ema_fast < ema_slow and (macd_hist is None or macd_hist <= 0):
        trend = "bearish"
    else:
        trend = "mixed"

    if price is None or ema_medium is None:
        price_position = "unknown"
    elif price >= ema_medium:
        price_position = "above_ema_medium"
    else:
        price_position = "below_ema_medium"

    return {
        "price": price,
        "rsi": rsi,
        "rsi_zone": rsi_zone,
        "ema_fast": ema_fast,
        "ema_medium": ema_medium,
        "ema_slow": ema_slow,
        "macd_hist": macd_hist,
        "trend": trend,
        "price_position": price_position,
    }


def _baseline_rule_summary(baseline: dict[str, Any]) -> dict[str, Any]:
    rules = [rule for rule in baseline.get("rules") or [] if isinstance(rule, dict)]
    fields: set[str] = set()
    directions: set[str] = set()
    for rule in rules:
        direction = str(rule.get("direction") or "").strip()
        if direction:
            directions.add(direction)
        cond = rule.get("condition") or {}
        if isinstance(cond, dict) and cond.get("field"):
            fields.add(str(cond["field"]))
        rule_fields = rule.get("fields") or {}
        if isinstance(rule_fields, dict):
            fields.update(str(value) for value in rule_fields.values() if str(value).strip())
    return {
        "rule_count": len(rules),
        "directions": sorted(directions),
        "fields": sorted(fields),
    }


def _baseline_for_agent(baseline: dict[str, Any]) -> dict[str, Any]:
    rules = [rule for rule in baseline.get("rules") or [] if isinstance(rule, dict)]
    summarized_rules: list[dict[str, Any]] = []
    for rule in rules[:12]:
        condition = rule.get("condition") if isinstance(rule.get("condition"), dict) else {}
        summarized_rules.append(
            {
                "name": rule.get("name"),
                "direction": rule.get("direction"),
                "strength": rule.get("strength"),
                "cooldown": rule.get("cooldown"),
                "condition": {
                    "type": condition.get("type"),
                    "field": condition.get("field"),
                    "threshold": condition.get("threshold"),
                },
            }
        )
    return {
        "name": baseline.get("name"),
        "market": baseline.get("market"),
        "symbols": baseline.get("symbols"),
        "timeframe": baseline.get("timeframe"),
        "thresholds": baseline.get("thresholds"),
        "indicators": baseline.get("indicators"),
        "rule_summary": _baseline_rule_summary(baseline),
        "rules": summarized_rules,
    }


def _reason_flags(previous_rejected_reasons: list[str]) -> dict[str, bool]:
    text = " | ".join(previous_rejected_reasons).lower()
    return {
        "too_many_signals": "too many signals" in text or "overtrade" in text,
        "low_activity": "no paper trades" in text or "no trades" in text or "no signals" in text,
        "underperformed": "underperformed baseline" in text or "underperformed baseline return" in text,
        "backtest_failed": "backtest failed" in text,
        "drawdown_worse": "max drawdown worse" in text or "drawdown" in text,
        "low_win_rate": "low win rate" in text or "win rate" in text,
        "paper_rejected": "risk limit" in text or "reject" in text or "rejected" in text,
    }


def _paper_report_data(report: dict[str, Any]) -> dict[str, Any]:
    data = report.get("data") if isinstance(report, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


def _summarize_paper_report(report: dict[str, Any]) -> dict[str, Any]:
    data = _paper_report_data(report)
    positions = data.get("positions") if isinstance(data.get("positions"), list) else []
    orders = data.get("recent_orders") if isinstance(data.get("recent_orders"), list) else []
    rejects = data.get("recent_rejects") if isinstance(data.get("recent_rejects"), list) else []
    notes: list[str] = []

    def number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    pnl_pct = number(data.get("pnl_pct"))
    if pnl_pct is not None:
        notes.append(f"paper_pnl_pct={pnl_pct:.4f}")
    pnl = number(data.get("pnl"))
    if pnl is not None:
        notes.append(f"paper_pnl={pnl:.4f}")
    notes.append(f"paper_positions={len(positions)}")
    notes.append(f"paper_recent_orders={len(orders)}")
    notes.append(f"paper_recent_rejects={len(rejects)}")

    reject_reasons: list[str] = []
    for item in rejects[:3]:
        if not isinstance(item, dict):
            continue
        reason = item.get("reason") or item.get("message") or item.get("error") or item.get("reject_reason")
        if reason:
            reject_reasons.append(str(reason))
    if reject_reasons:
        notes.append(f"paper_reject_reasons={'; '.join(reject_reasons)}")

    return {
        "available": bool(report.get("ok")) or bool(data),
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "positions_count": len(positions),
        "recent_orders_count": len(orders),
        "recent_rejects_count": len(rejects),
        "recent_reject_reasons": reject_reasons,
        "negative_pnl": bool(pnl_pct is not None and pnl_pct < 0) or bool(pnl is not None and pnl < 0),
        "has_rejects": bool(rejects),
        "notes": notes,
    }


def _summarize_news_context(news_payload: dict[str, Any]) -> dict[str, Any]:
    articles = news_payload.get("data") if isinstance(news_payload.get("data"), list) else []
    titles: list[str] = []
    symbols: set[str] = set()
    categories: set[str] = set()
    providers: set[str] = set()
    for item in articles[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title:
            titles.append(title[:160])
        for symbol in item.get("symbols") or []:
            if str(symbol).strip():
                symbols.add(str(symbol).strip())
        category = str(item.get("category") or "").strip()
        if category:
            categories.add(category)
        provider = str(item.get("provider") or "").strip()
        if provider:
            providers.add(provider)

    notes = [f"news_articles={len(articles)}"]
    if titles:
        notes.append(f"news_titles={' | '.join(titles[:3])}")
    if symbols:
        notes.append(f"news_symbols={','.join(sorted(symbols)[:5])}")
    if categories:
        notes.append(f"news_categories={','.join(sorted(categories)[:5])}")

    return {
        "available": bool(news_payload.get("ok")) and bool(articles),
        "article_count": len(articles),
        "titles": titles,
        "symbols": sorted(symbols),
        "categories": sorted(categories),
        "providers": sorted(providers),
        "notes": notes,
    }


def _summary_int(summary: dict[str, Any], key: str) -> int:
    value = _number(summary.get(key))
    return int(value) if value is not None else 0


def _summarize_risk_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, dict) or not summary:
        return {"available": False}

    risk_flags = [str(item).strip() for item in summary.get("risk_flags") or [] if str(item).strip()]
    risk_level = str(summary.get("risk_level") or "unknown")
    max_exposure = _number(summary.get("max_exposure_pct"))
    max_drawdown = _number(summary.get("max_drawdown_pct"))
    min_return = _number(summary.get("min_return_pct"))
    max_signals = _number(summary.get("max_signals_total"))
    risk_by_round = summary.get("risk_by_round") if isinstance(summary.get("risk_by_round"), list) else []

    notes = [f"risk_level={risk_level}"]
    if summary.get("scope"):
        notes.append(f"risk_scope={summary.get('scope')}")
    if risk_flags:
        notes.append(f"risk_flags={'; '.join(risk_flags[:5])}")
    if max_exposure is not None:
        notes.append(f"max_exposure_pct={max_exposure:.4f}")
    if max_drawdown is not None:
        notes.append(f"max_drawdown_pct={max_drawdown:.4f}")
    if min_return is not None:
        notes.append(f"min_return_pct={min_return:.4f}")
    if max_signals is not None:
        notes.append(f"max_signals_total={int(max_signals)}")

    return {
        "available": True,
        "scope": summary.get("scope"),
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "candidate_count": _summary_int(summary, "candidate_count"),
        "eligible_count": _summary_int(summary, "eligible_count"),
        "rejected_count": _summary_int(summary, "rejected_count"),
        "failed_count": _summary_int(summary, "failed_count"),
        "max_exposure_pct": max_exposure,
        "max_drawdown_pct": max_drawdown,
        "min_return_pct": min_return,
        "max_signals_total": int(max_signals) if max_signals is not None else None,
        "high_risk": risk_level == "high",
        "has_failures": _summary_int(summary, "failed_count") > 0 or any("failed" in flag.lower() for flag in risk_flags),
        "has_rejections": _summary_int(summary, "rejected_count") > 0,
        "risk_by_round": [
            {
                "round": item.get("round"),
                "risk_level": item.get("risk_level"),
                "risk_flags": item.get("risk_flags") or [],
            }
            for item in risk_by_round[:5]
            if isinstance(item, dict)
        ],
        "notes": notes,
    }


def _summarize_repair_guidance(items: list[str] | None) -> dict[str, Any]:
    guidance = _dedupe_strings([str(item) for item in items or []])
    return {
        "available": bool(guidance),
        "items": guidance,
        "notes": [f"repair_guidance={'; '.join(guidance[:5])}"] if guidance else [],
    }


def _context_health(context: dict[str, Any] | None) -> dict[str, Any]:
    ctx = context or {}
    quote_items = ((ctx.get("quotes") or {}).get("data") or []) if isinstance(ctx.get("quotes") or {}, dict) else []
    quote = quote_items[0] if quote_items and isinstance(quote_items[0], dict) else {}
    indicators_payload = (ctx.get("indicators") or {}).get("data") if isinstance(ctx.get("indicators") or {}, dict) else {}
    indicators = indicators_payload if isinstance(indicators_payload, dict) else {}
    indicator_values = indicators.get("indicators") if isinstance(indicators.get("indicators"), dict) else {}
    news_present = "news" in ctx
    news_feedback = _summarize_news_context(ctx.get("news") if isinstance(ctx.get("news"), dict) else {})
    warnings = ctx.get("warnings") if isinstance(ctx.get("warnings"), list) else []
    warning_sources = _dedupe_strings(
        [str(item.get("source") or "unknown") for item in warnings if isinstance(item, dict)]
    )

    quote_available = bool(quote.get("ok")) or _number(quote.get("price")) is not None
    indicator_available = bool(indicator_values) or _number(indicators.get("close")) is not None
    market_data_ready = quote_available and indicator_available
    missing_inputs: list[str] = []
    if not quote_available:
        missing_inputs.append("quote")
    if not indicator_available:
        missing_inputs.append("indicators")
    if news_present and not news_feedback.get("available"):
        missing_inputs.append("news")

    if market_data_ready and (not news_present or news_feedback.get("available")):
        quality = "ready"
    elif quote_available or indicator_available:
        quality = "partial"
    else:
        quality = "limited"

    notes = [
        f"context_quality={quality}",
        f"quote_available={str(quote_available).lower()}",
        f"indicator_available={str(indicator_available).lower()}",
        f"news_requested={str(news_present).lower()}",
    ]
    if missing_inputs:
        notes.append(f"missing_inputs={','.join(missing_inputs)}")
    if warning_sources:
        notes.append(f"warning_sources={','.join(warning_sources)}")

    return {
        "available": True,
        "quality": quality,
        "market_data_ready": market_data_ready,
        "quote_available": quote_available,
        "indicator_available": indicator_available,
        "news_requested": news_present,
        "news_available": bool(news_feedback.get("available")),
        "warning_count": len(warnings),
        "warning_sources": warning_sources,
        "missing_inputs": missing_inputs,
        "notes": notes,
        "note": "Read-only context quality summary; not a promotion gate or trading signal.",
    }


def _context_for_agent(context: dict[str, Any], *, symbol: str) -> dict[str, Any]:
    indicators = ((context.get("indicators") or {}).get("data") or {})
    quote_items = ((context.get("quotes") or {}).get("data") or [])
    quote = quote_items[0] if quote_items and isinstance(quote_items[0], dict) else {}
    health = _context_health(context)
    return {
        "symbol": symbol,
        "quote": {
            "ok": quote.get("ok"),
            "price": quote.get("price"),
            "prev_close": quote.get("prev_close"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "volume": quote.get("volume"),
            "amount": quote.get("amount"),
            "provider": quote.get("provider"),
            "quote_ts": quote.get("quote_ts"),
        },
        "indicators": {
            "timeframe": indicators.get("timeframe"),
            "bar_ts": indicators.get("bar_ts"),
            "close": indicators.get("close"),
            "values": indicators.get("indicators") or {},
        },
        "watchlist_ranking": context.get("watchlist_ranking") or [],
        "paper_feedback": context.get("previous_paper_feedback") or context.get("paper_feedback"),
        "risk_feedback": context.get("previous_risk_feedback")
        or context.get("risk_feedback")
        or _summarize_risk_summary(
            context.get("previous_risk_summary")
            or context.get("portfolio_risk_summary")
            or context.get("loop_risk_summary")
            or {}
        ),
        "repair_feedback": context.get("previous_repair_feedback")
        or context.get("repair_feedback")
        or _summarize_repair_guidance(context.get("previous_repair_guidance") or []),
        "news_feedback": context.get("news_feedback") or _summarize_news_context(context.get("news") or {}),
        "context_health": health,
        "warnings": context.get("warnings") or [],
    }


def _agent_feedback_block(*, agent_context: dict[str, Any], previous_rejected_reasons: list[str]) -> dict[str, Any]:
    rejected = [str(item).strip() for item in previous_rejected_reasons if str(item).strip()]
    paper_feedback = agent_context.get("paper_feedback") or {"available": False}
    risk_feedback = agent_context.get("risk_feedback") or {"available": False}
    repair_feedback = agent_context.get("repair_feedback") or {"available": False}
    news_feedback = agent_context.get("news_feedback") or {"available": False}
    context_health = agent_context.get("context_health") or {"available": False}
    priority: list[str] = []
    notes: list[str] = []

    if repair_feedback.get("available"):
        priority.append("fix previous validation repair guidance before changing strategy intent")
        notes.extend(str(item) for item in repair_feedback.get("notes") or [])
    if isinstance(context_health, dict) and context_health.get("available"):
        if not context_health.get("market_data_ready"):
            priority.append("market context is incomplete; avoid assumptions from missing quote or indicator data")
        notes.extend(str(item) for item in context_health.get("notes") or [])
    if risk_feedback.get("available"):
        level = str(risk_feedback.get("risk_level") or "")
        if level in {"medium", "high"}:
            priority.append(f"address {level} risk feedback without increasing exposure or signal frequency")
        notes.extend(str(item) for item in risk_feedback.get("notes") or [])
    if isinstance(paper_feedback, dict) and paper_feedback.get("available"):
        if paper_feedback.get("negative_pnl"):
            priority.append("paper feedback shows negative pnl; tighten entries and reduce noisy signals")
        if paper_feedback.get("has_rejects"):
            priority.append("paper feedback shows rejected orders; reduce order pressure")
        notes.extend(str(item) for item in paper_feedback.get("notes") or [])
    if rejected:
        priority.append("address previous rejected reasons")
        notes.append(f"previous_rejected_reasons={'; '.join(rejected[:5])}")
    if isinstance(news_feedback, dict) and news_feedback.get("available"):
        notes.extend(str(item) for item in news_feedback.get("notes") or [])

    return {
        "available": bool(priority or notes),
        "priority": _dedupe_strings(priority),
        "previous_rejected_reasons": rejected,
        "paper_feedback": paper_feedback,
        "risk_feedback": risk_feedback,
        "repair_feedback": repair_feedback,
        "context_health": context_health,
        "news_feedback": news_feedback,
        "notes": _dedupe_strings(notes),
        "note": "Unified read-only feedback for candidate generation; not a promotion gate or trading signal.",
    }


def _agent_candidate_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["candidates"],
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 2,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "required": ["id", "hypothesis", "changes", "content"],
                    "properties": {
                        "id": {"type": "string"},
                        "hypothesis": {"type": "string"},
                        "changes": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "content": {"type": "string", "description": "StrategyConfig-compatible YAML"},
                    },
                },
            }
        },
    }


def _agent_response_template(*, symbol: str, candidate_count: int) -> dict[str, Any]:
    count = max(2, min(5, int(candidate_count)))
    example_yaml = (
        "name: Agent candidate example\n"
        "market: crypto_spot\n"
        "symbols:\n"
        f"  - {symbol}\n"
        "timeframe: 5m\n"
        "thresholds:\n"
        "  min_strength: 60\n"
        "rules:\n"
        "  - name: RSI pullback confirmation\n"
        "    direction: BUY\n"
        "    strength: 60\n"
        "    cooldown: 600\n"
        "    condition:\n"
        "      type: indicator\n"
        "      field: rsi\n"
        "      op: lt\n"
        "      threshold: 35\n"
    )
    return {
        "artifact_type": "agent_response_template",
        "purpose": "Fill this JSON shape and submit it via --agent-candidates. This file is not a candidate strategy.",
        "submit_via": "tradecat_strategy_evolve.py --agent-candidates <json-or-file>",
        "target_symbol": symbol,
        "candidate_count": count,
        "schema": _agent_candidate_schema(),
        "template": {
            "candidates": [
                {
                    "id": f"candidate_{index:02d}",
                    "hypothesis": "State what market behavior this candidate is testing.",
                    "changes": [
                        "Describe one concrete parameter or rule change.",
                        "Describe why this change addresses prompt context or risk feedback.",
                    ],
                    "content": example_yaml,
                }
                for index in range(1, count + 1)
            ]
        },
        "validation_checklist": [
            "Return JSON only, with a top-level candidates array.",
            "Provide 2 to 5 candidates.",
            "Every candidate must include id, hypothesis, changes, and content.",
            "content must be StrategyConfig-compatible YAML.",
            f"Strategy symbols must contain only {symbol}; the system will force this again before validation.",
            "Rules must use BUY or SELL direction.",
            "Rule strength must stay between 30 and 95.",
            "Rule cooldown must stay between 60 and 3600 seconds.",
            "RSI thresholds must stay between 10 and 90.",
            "Do not include paper activation, live trading instructions, file paths, or watchlist expansion.",
        ],
    }


def _optional_artifact_path(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return _artifact_rel(path)


def _agent_next_action(
    *,
    status: str,
    context_health: dict[str, Any],
    repair_guidance: list[str],
    agent_feedback: dict[str, Any],
) -> dict[str, Any]:
    repair_feedback = agent_feedback.get("repair_feedback") if isinstance(agent_feedback.get("repair_feedback"), dict) else {}
    needs_repair = bool(repair_guidance) or bool(repair_feedback.get("available"))
    market_data_ready = bool(context_health.get("market_data_ready"))
    failure_statuses = {"agent_draft_rejected", "candidate_static_sanity_failed", "candidate_write_failed"}
    reasons: list[str] = []

    if status in failure_statuses:
        reasons.append(f"handoff_status={status}")
    if needs_repair:
        reasons.append("repair feedback is available")
    if context_health.get("available") and not market_data_ready:
        reasons.append("market context is incomplete")

    if status in failure_statuses or needs_repair:
        action = "repair_candidate_drafts"
        readiness = "repair_required"
        candidate_style = "repair_first"
    elif context_health.get("available") and not market_data_ready:
        action = "generate_conservative_candidates"
        readiness = "degraded_context"
        candidate_style = "conservative"
    else:
        action = "generate_candidate_drafts"
        readiness = "ready"
        candidate_style = "normal"

    return {
        "action": action,
        "readiness": readiness,
        "candidate_style": candidate_style,
        "requires_agent_candidates": True,
        "submit_via": "tradecat_strategy_evolve.py --agent-candidates <json-or-file>",
        "reasons": _dedupe_strings(reasons),
        "blocked": False,
        "note": "Read-only automation hint for external Agent handoff; not a promotion gate or trading signal.",
    }


def _agent_submission_hint(
    *,
    strategy: str,
    symbol: str,
    watchlist: list[str],
    market: str,
    days: int,
    timeframe: str,
    provider: str,
    min_strength: int,
    initial_equity: float | None,
    notional: float | None,
    mode: str,
    candidate_count: int,
    include_news: bool,
    news_limit: int,
    news_since_minutes: int,
    timeout: float,
    agent_next_action: dict[str, Any],
) -> dict[str, Any]:
    watchlist_arg = ",".join(watchlist)
    safe_candidate_count = max(2, min(5, int(candidate_count)))

    def optional_arg(args: list[str], name: str, value: object) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text:
            args.extend([name, text])

    def command(submit_mode: str) -> list[str]:
        args = [
            "python3",
            "scripts/tradecat_strategy_evolve.py",
            "--strategy",
            strategy,
            "--symbol",
            symbol,
            "--watchlist",
            watchlist_arg,
            "--days",
            str(int(days)),
            "--min-strength",
            str(int(min_strength)),
            "--mode",
            submit_mode,
            "--candidate-count",
            str(safe_candidate_count),
            "--timeout",
            str(timeout),
        ]
        optional_arg(args, "--market", market)
        optional_arg(args, "--timeframe", timeframe)
        optional_arg(args, "--provider", provider)
        optional_arg(args, "--initial-equity", initial_equity)
        optional_arg(args, "--notional", notional)
        if include_news:
            args.append("--include-news")
            args.extend(
                [
                    "--news-limit",
                    str(int(news_limit)),
                    "--news-since-minutes",
                    str(int(news_since_minutes)),
                ]
            )
        args.extend(
            [
                "--agent-candidates",
                "<json-or-file>",
            ]
        )
        return args

    submission_context = {
        "strategy": strategy,
        "symbol": symbol,
        "watchlist": watchlist,
        "market": market or None,
        "days": int(days),
        "timeframe": timeframe or None,
        "provider": provider or None,
        "min_strength": int(min_strength),
        "initial_equity": initial_equity,
        "notional": notional,
        "candidate_count": safe_candidate_count,
        "include_news": bool(include_news),
        "news_limit": int(news_limit),
        "news_since_minutes": int(news_since_minutes),
        "timeout": timeout,
        "agent_candidates": "<json-or-file>",
    }

    context_args = [
        "--strategy",
        "--symbol",
        "--watchlist",
        "--days",
        "--min-strength",
        "--candidate-count",
        "--timeout",
    ]
    if market:
        context_args.append("--market")
    if timeframe:
        context_args.append("--timeframe")
    if provider:
        context_args.append("--provider")
    if initial_equity is not None:
        context_args.append("--initial-equity")
    if notional is not None:
        context_args.append("--notional")
    if include_news:
        context_args.extend(
            [
                "--include-news",
                "--news-limit",
                "--news-since-minutes",
            ]
        )

    verify_mode = mode if mode in {"suggest", "dry_run"} else "dry_run"
    if verify_mode == "suggest":
        verify_mode = "dry_run"
    readiness = str(agent_next_action.get("readiness") or "")
    recommended = "safe_suggest" if readiness in {"repair_required", "degraded_context"} else "dry_run_verify"
    return {
        "artifact_type": "agent_submission_hint",
        "candidate_payload": "JSON matching agent_response_template.json with a top-level candidates array.",
        "submission_context": submission_context,
        "context_preserved_args": context_args,
        "recommended": recommended,
        "safe_suggest": {
            "mode": "suggest",
            "command_argv": command("suggest"),
            "purpose": "Validate handoff shape and write prompt-ready artifacts without promotion.",
        },
        "dry_run_verify": {
            "mode": verify_mode,
            "command_argv": command(verify_mode),
            "purpose": "Validate, write, backtest, and compare candidates without changing current.",
        },
        "omitted_args": {
            "--run-id": "omitted by default to avoid overwriting this handoff run",
            "--mode paper": "omitted; paper requires explicit user request",
        },
        "note": "Read-only submission hint for external Agent output; command templates preserve request context and are not executed by this artifact.",
    }


def _agent_handoff_bundle(
    *,
    run_id: str,
    mode: str,
    strategy: str,
    symbol: str,
    watchlist: list[str],
    generator_source: str,
    candidate_count: int,
    status: str,
    handoff_path: Path,
    agent_prompt_path: Path,
    agent_feedback_path: Path,
    agent_response_template_path: Path,
    agent_response_path: Path | None,
    agent_response_validation_path: Path | None,
    agent_feedback: dict[str, Any],
    context_health: dict[str, Any],
    agent_next_action: dict[str, Any],
    agent_submission: dict[str, Any],
    repair_guidance: list[str],
) -> dict[str, Any]:
    files = {
        "agent_handoff": _artifact_rel(handoff_path),
        "agent_prompt": _artifact_rel(agent_prompt_path),
        "agent_feedback": _artifact_rel(agent_feedback_path),
        "agent_response_template": _artifact_rel(agent_response_template_path),
        "agent_response": _optional_artifact_path(agent_response_path),
        "agent_response_validation": _optional_artifact_path(agent_response_validation_path),
    }
    read_order = ["agent_prompt", "agent_feedback", "agent_response_template"]
    if files["agent_response"]:
        read_order.append("agent_response")
    if files["agent_response_validation"]:
        read_order.append("agent_response_validation")

    return {
        "artifact_type": "agent_handoff",
        "purpose": "Index of prompt-ready artifacts for external Agent candidate generation. Read-only; not a promotion gate.",
        "run_id": run_id,
        "status": status,
        "mode": mode,
        "input_strategy": strategy,
        "target_symbol": symbol,
        "watchlist": watchlist,
        "generator_source": generator_source,
        "candidate_count": max(2, min(5, int(candidate_count))),
        "files": files,
        "next_agent_contract": {
            "read_order": read_order,
            "required_inputs": ["agent_prompt", "agent_feedback", "agent_response_template"],
            "optional_inputs": ["agent_response", "agent_response_validation"],
            "submit_via": "tradecat_strategy_evolve.py --agent-candidates <json-or-file>",
            "repair_guidance": repair_guidance,
            "context_health": context_health,
            "agent_next_action": agent_next_action,
            "agent_submission": agent_submission,
        },
        "context_health": context_health,
        "agent_next_action": agent_next_action,
        "agent_submission": agent_submission,
        "agent_feedback_summary": {
            "available": bool(agent_feedback.get("available")),
            "priority": agent_feedback.get("priority") or [],
            "notes": agent_feedback.get("notes") or [],
        },
        "safety_constraints": [
            "Generate candidate drafts only; do not activate paper or live trading.",
            "Do not change config/strategies/current.",
            "Do not expand the watchlist or scan the full market.",
            "News, when present, is read-only context and not a direct buy/sell trigger.",
            "Final selection remains controlled by validation, backtest, compare, and promotion gates.",
        ],
    }


def _write_agent_handoff_artifact(
    *,
    artifact_dir: Path,
    run_id: str,
    mode: str,
    strategy: str,
    symbol: str,
    watchlist: list[str],
    generator_source: str,
    candidate_count: int,
    status: str,
    agent_prompt_path: Path,
    agent_feedback_path: Path,
    agent_response_template_path: Path,
    agent_response_path: Path | None,
    agent_response_validation_path: Path | None,
    agent_feedback: dict[str, Any],
    context_health: dict[str, Any],
    agent_next_action: dict[str, Any],
    agent_submission: dict[str, Any],
    repair_guidance: list[str],
) -> Path:
    handoff_path = artifact_dir / "agent_handoff.json"
    _write_json(
        handoff_path,
        _agent_handoff_bundle(
            run_id=run_id,
            mode=mode,
            strategy=strategy,
            symbol=symbol,
            watchlist=watchlist,
            generator_source=generator_source,
            candidate_count=candidate_count,
            status=status,
            handoff_path=handoff_path,
            agent_prompt_path=agent_prompt_path,
            agent_feedback_path=agent_feedback_path,
            agent_response_template_path=agent_response_template_path,
            agent_response_path=agent_response_path,
            agent_response_validation_path=agent_response_validation_path,
            agent_feedback=agent_feedback,
            context_health=context_health,
            agent_next_action=agent_next_action,
            agent_submission=agent_submission,
            repair_guidance=repair_guidance,
        ),
    )
    return handoff_path


def _build_agent_prompt_pack(
    *,
    run_id: str,
    strategy: str,
    baseline: dict[str, Any],
    symbol: str,
    watchlist: list[str],
    context: dict[str, Any],
    candidate_count: int,
    previous_rejected_reasons: list[str],
) -> dict[str, Any]:
    agent_context = _context_for_agent(context, symbol=symbol)
    agent_feedback = _agent_feedback_block(agent_context=agent_context, previous_rejected_reasons=previous_rejected_reasons)
    agent_context["agent_feedback"] = agent_feedback
    context_health = agent_context.get("context_health") or _context_health(context)
    return {
        "run_id": run_id,
        "objective": "Generate candidate strategy YAML drafts for the validation loop.",
        "input_strategy": strategy,
        "target_symbol": symbol,
        "watchlist": watchlist,
        "candidate_count": max(2, min(5, int(candidate_count))),
        "output_contract": {
            "format": "json",
            "schema": _agent_candidate_schema(),
            "template_artifact": "agent_response_template.json",
            "submit_via": "tradecat_strategy_evolve.py --agent-candidates <json-or-file>",
        },
        "safety_constraints": [
            "Return candidate drafts only; do not activate paper or live trading.",
            "Use the existing StrategyConfig YAML shape; do not invent a new DSL.",
            "Generate candidates only for target_symbol; the system will force symbols to target_symbol.",
            "Do not expand the watchlist or scan the full market.",
            "News, when present, is context only and must not be a direct buy/sell trigger.",
            "Every candidate must include hypothesis and concrete changes.",
            "Final selection is decided only by validate/write/backtest/compare/promotion gates.",
        ],
        "baseline": _baseline_for_agent(baseline),
        "context": agent_context,
        "context_health": context_health,
        "agent_feedback": agent_feedback,
        "agent_feedback_artifact": "agent_feedback.json",
        "previous_rejected_reasons": previous_rejected_reasons,
        "generation_guidance": [
            "Create 2 to 5 meaningfully different candidates.",
            "Prefer small, explainable changes to thresholds, cooldowns, and confirmations.",
            "If previous rejected reasons mention overtrading or high exposure, reduce signal frequency.",
            "If previous rejected reasons mention no trades or no signals, widen entries cautiously.",
            "If previous rejected reasons mention drawdown or weak win rate, tighten entries and reduce exposure.",
            "If risk_feedback is medium or high, address its risk_flags directly without increasing exposure or signal frequency.",
            "If repair_feedback is available, fix those validation issues before introducing new strategy ideas.",
            "If context_health.market_data_ready is false, keep changes conservative and do not infer missing market state.",
            "Use agent_feedback.priority as the highest-level summary of what the next candidates should address.",
        ],
    }


def _generator_context(
    *,
    baseline: dict[str, Any],
    context: dict[str, Any] | None,
    previous_rejected_reasons: list[str] | None,
) -> dict[str, Any]:
    reasons = [str(reason).strip() for reason in previous_rejected_reasons or [] if str(reason).strip()]
    indicator_context = _extract_indicator_context(context)
    rule_summary = _baseline_rule_summary(baseline)
    flags = _reason_flags(reasons)
    notes: list[str] = []
    if indicator_context["rsi"] is not None:
        notes.append(f"RSI={indicator_context['rsi']:.2f} ({indicator_context['rsi_zone']})")
    notes.append(f"trend={indicator_context['trend']}")
    if indicator_context["macd_hist"] is not None:
        notes.append(f"MACD_hist={indicator_context['macd_hist']:.4f}")
    if indicator_context["price_position"] != "unknown":
        notes.append(f"price={indicator_context['price_position']}")
    if reasons:
        notes.append(f"previous_rejected_reasons={'; '.join(reasons[:3])}")
    paper_report = (context or {}).get("previous_paper_report") or (context or {}).get("paper_report") or {}
    paper_feedback = _summarize_paper_report(paper_report if isinstance(paper_report, dict) else {})
    if paper_feedback["available"]:
        notes.extend(paper_feedback["notes"])
    news_context = (context or {}).get("news") or {}
    news_feedback = _summarize_news_context(news_context if isinstance(news_context, dict) else {})
    if "news" in (context or {}):
        notes.extend(news_feedback["notes"])
    risk_source = (
        (context or {}).get("previous_risk_summary")
        or (context or {}).get("portfolio_risk_summary")
        or (context or {}).get("loop_risk_summary")
        or {}
    )
    risk_feedback = (context or {}).get("previous_risk_feedback") or _summarize_risk_summary(risk_source)
    if risk_feedback["available"]:
        notes.extend(risk_feedback["notes"])
    repair_feedback = (context or {}).get("previous_repair_feedback") or _summarize_repair_guidance(
        (context or {}).get("previous_repair_guidance") or []
    )
    if repair_feedback["available"]:
        notes.extend(repair_feedback["notes"])
    agent_feedback = _agent_feedback_block(
        agent_context={
            "paper_feedback": paper_feedback,
            "risk_feedback": risk_feedback,
            "repair_feedback": repair_feedback,
            "news_feedback": news_feedback,
        },
        previous_rejected_reasons=reasons,
    )
    return {
        **indicator_context,
        "baseline": rule_summary,
        "previous_rejected_reasons": reasons,
        "reason_flags": flags,
        "paper_feedback": paper_feedback,
        "risk_feedback": risk_feedback,
        "repair_feedback": repair_feedback,
        "agent_feedback": agent_feedback,
        "news_feedback": news_feedback,
        "notes": notes,
    }


def _candidate_plans(gen_ctx: dict[str, Any]) -> list[dict[str, Any]]:
    flags = gen_ctx.get("reason_flags") or {}
    paper_feedback = gen_ctx.get("paper_feedback") or {}
    trend = gen_ctx.get("trend")
    rsi_zone = gen_ctx.get("rsi_zone")
    notes = gen_ctx.get("notes") or []
    context_note = "; ".join(notes) if notes else "context unavailable"
    plans: list[dict[str, Any]] = []

    if flags.get("drawdown_worse"):
        plans.append(
            {
                "hypothesis": f"Previous candidate had worse drawdown; reduce exposure and require stronger confirmation. Context: {context_note}.",
                "ops": ["raise_strength", "raise_cooldown", "tighten_rsi"],
                "plan_reasons": ["previous rejected: drawdown worse than baseline", *notes],
            }
        )
    elif flags.get("low_win_rate"):
        plans.append(
            {
                "hypothesis": f"Previous candidate had weak win rate; trade fewer setups with cleaner RSI confirmation. Context: {context_note}.",
                "ops": ["raise_strength", "tighten_rsi"],
                "plan_reasons": ["previous rejected: low win rate", *notes],
            }
        )
    elif flags.get("paper_rejected") or paper_feedback.get("has_rejects"):
        plans.append(
            {
                "hypothesis": f"Paper feedback shows rejected trades; reduce order pressure and tighten entries before retesting. Context: {context_note}.",
                "ops": ["raise_strength", "raise_cooldown", "tighten_rsi"],
                "plan_reasons": ["paper feedback: rejected trades", *notes],
            }
        )
    elif paper_feedback.get("negative_pnl"):
        ops = ["raise_strength", "raise_cooldown"]
        if trend == "bullish":
            ops += ["relax_buy_rsi", "tighten_sell_rsi"]
        elif trend == "bearish":
            ops += ["tighten_buy_rsi", "relax_sell_rsi"]
        else:
            ops.append("tighten_rsi")
        plans.append(
            {
                "hypothesis": f"Paper feedback is negative; keep fewer, more context-aligned signals. Context: {context_note}.",
                "ops": ops,
                "plan_reasons": ["paper feedback: negative pnl", *notes],
            }
        )
    elif flags.get("too_many_signals"):
        plans.append(
            {
                "hypothesis": f"Previous run produced too many signals; reduce noise before retesting. Context: {context_note}.",
                "ops": ["raise_strength", "raise_cooldown", "tighten_rsi"],
                "plan_reasons": ["previous rejected: too many signals", *notes],
            }
        )
    elif flags.get("low_activity"):
        plans.append(
            {
                "hypothesis": f"Previous run had too few trades/signals; widen entries carefully. Context: {context_note}.",
                "ops": ["lower_strength", "lower_cooldown", "relax_rsi"],
                "plan_reasons": ["previous rejected: low activity", *notes],
            }
        )
    elif flags.get("underperformed"):
        ops = ["raise_strength", "raise_cooldown"]
        if trend == "bullish":
            ops += ["relax_buy_rsi", "tighten_sell_rsi"]
        elif trend == "bearish":
            ops += ["tighten_buy_rsi", "relax_sell_rsi"]
        else:
            ops.append("tighten_rsi")
        plans.append(
            {
                "hypothesis": f"Previous run underperformed baseline; keep fewer, more context-aligned signals. Context: {context_note}.",
                "ops": ops,
                "plan_reasons": ["previous rejected: underperformed baseline", *notes],
            }
        )

    if trend == "bullish":
        plans.append(
            {
                "hypothesis": f"Bullish indicator context; test pullback entries while avoiding early exits. Context: {context_note}.",
                "ops": ["lower_strength", "relax_buy_rsi", "tighten_sell_rsi"],
                "plan_reasons": ["context trend: bullish", *notes],
            }
        )
    elif trend == "bearish":
        plans.append(
            {
                "hypothesis": f"Bearish indicator context; require deeper buy setup and allow earlier sell response. Context: {context_note}.",
                "ops": ["raise_strength", "tighten_buy_rsi", "relax_sell_rsi", "raise_cooldown"],
                "plan_reasons": ["context trend: bearish", *notes],
            }
        )
    else:
        plans.append(
            {
                "hypothesis": f"Mixed indicator context; reduce noisy trades with stricter confirmation. Context: {context_note}.",
                "ops": ["raise_strength", "raise_cooldown", "tighten_rsi"],
                "plan_reasons": ["context trend: mixed/unknown", *notes],
            }
        )

    if rsi_zone == "overbought":
        plans.append(
            {
                "hypothesis": f"RSI is overbought; test stricter buys and more responsive sells. Context: {context_note}.",
                "ops": ["raise_strength", "tighten_buy_rsi", "relax_sell_rsi"],
                "plan_reasons": ["context RSI: overbought", *notes],
            }
        )
    elif rsi_zone == "oversold":
        plans.append(
            {
                "hypothesis": f"RSI is oversold; test earlier rebound entries with sell guardrails. Context: {context_note}.",
                "ops": ["lower_strength", "relax_buy_rsi", "tighten_sell_rsi"],
                "plan_reasons": ["context RSI: oversold", *notes],
            }
        )
    else:
        plans.append(
            {
                "hypothesis": f"RSI is neutral or unavailable; test anti-overtrade cooldown control. Context: {context_note}.",
                "ops": ["raise_cooldown"],
                "plan_reasons": ["context RSI: neutral/unknown", *notes],
            }
        )

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for plan in plans:
        key = tuple(plan["ops"])
        if key not in seen:
            seen.add(key)
            unique.append(plan)
    return unique


def _generate_candidates(
    *,
    baseline: dict[str, Any],
    symbol: str,
    run_id: str,
    count: int,
    context: dict[str, Any] | None = None,
    previous_rejected_reasons: list[str] | None = None,
) -> list[dict[str, Any]]:
    gen_ctx = _generator_context(
        baseline=baseline,
        context=context,
        previous_rejected_reasons=previous_rejected_reasons,
    )
    templates = _candidate_plans(gen_ctx)
    candidates: list[dict[str, Any]] = []
    for idx, template in enumerate(templates[:count], start=1):
        data = copy.deepcopy(baseline)
        _set_symbol(data, symbol)
        data["name"] = f"{baseline.get('name', 'Agent Strategy')} candidate {idx}"
        changes: list[str] = []
        for op in template["ops"]:
            if op == "raise_strength":
                changes.extend(_adjust_thresholds(data, +10))
            elif op == "lower_strength":
                changes.extend(_adjust_thresholds(data, -5))
            elif op == "raise_cooldown":
                changes.extend(_adjust_cooldown(data, +300))
            elif op == "tighten_rsi":
                changes.extend(_adjust_rsi_thresholds(data, tighten=True))
            elif op == "relax_rsi":
                changes.extend(_adjust_rsi_thresholds(data, tighten=False))
            elif op == "lower_cooldown":
                changes.extend(_adjust_cooldown(data, -120))
            elif op == "tighten_buy_rsi":
                changes.extend(_adjust_rsi_thresholds(data, buy_delta=-5))
            elif op == "relax_buy_rsi":
                changes.extend(_adjust_rsi_thresholds(data, buy_delta=3))
            elif op == "tighten_sell_rsi":
                changes.extend(_adjust_rsi_thresholds(data, sell_delta=5))
            elif op == "relax_sell_rsi":
                changes.extend(_adjust_rsi_thresholds(data, sell_delta=-3))
        if not changes:
            changes.append("No parameter changes were available for this strategy schema")
        name = _candidate_name(symbol, run_id, idx)
        candidates.append(
            {
                "strategy": name,
                "hypothesis": template["hypothesis"],
                "changes": changes,
                "generator_context": {
                    "source": "deterministic",
                    "notes": gen_ctx["notes"],
                    "baseline": gen_ctx["baseline"],
                    "previous_rejected_reasons": gen_ctx["previous_rejected_reasons"],
                    "reason_flags": gen_ctx["reason_flags"],
                    "paper_feedback": gen_ctx["paper_feedback"],
                    "news_feedback": gen_ctx["news_feedback"],
                    "plan_reasons": template.get("plan_reasons") or [],
                },
                "content": _dump_strategy(data),
            }
        )
    return candidates


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


def _manage_write(candidate: dict[str, Any], *, note: str) -> dict[str, Any]:
    code, payload = _run_json(
        [
            sys.executable,
            str(MANAGE_SCRIPT),
            "write",
            "--strategy",
            candidate["strategy"],
            "--content",
            candidate["content"],
            "--note",
            note,
        ],
        timeout=30,
    )
    return {"exit_code": code, **payload}


def _manage_use(strategy: str, *, note: str) -> dict[str, Any]:
    code, payload = _run_json(
        [
            sys.executable,
            str(MANAGE_SCRIPT),
            "use",
            "--strategy",
            strategy,
            "--note",
            note,
        ],
        timeout=60,
    )
    return {"exit_code": code, **payload}


def _paper_report(symbol: str) -> dict[str, Any]:
    if not PAPER_REPORT_SCRIPT.is_file():
        return {"ok": False, "error": _error_payload("not_found", "tradecat_agent_paper_report.py not found")}
    code, payload = _run_json(
        [
            sys.executable,
            str(PAPER_REPORT_SCRIPT),
            "--symbol",
            symbol,
        ],
        timeout=30,
    )
    return {"exit_code": code, **payload}


def _news_context(symbol: str, *, limit: int, since_minutes: int) -> dict[str, Any]:
    if not NEWS_SCRIPT.is_file():
        return {"ok": False, "error": _error_payload("not_found", "tradecat_get_news.py not found")}
    code, payload = _run_json(
        [
            sys.executable,
            str(NEWS_SCRIPT),
            "--symbol",
            symbol,
            "--limit",
            str(limit),
            "--since-minutes",
            str(since_minutes),
        ],
        timeout=90,
    )
    return {"exit_code": code, **payload}


def _compare(
    *,
    strategies: list[str],
    symbol: str,
    market: str,
    days: int,
    timeframe: str,
    provider: str,
    min_strength: int,
    initial_equity: float | None,
    notional: float | None,
    timeout: float,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(COMPARE_SCRIPT),
        "--strategies",
        ",".join(strategies),
        "--symbol",
        symbol,
        "--days",
        str(days),
        "--min-strength",
        str(min_strength),
        "--timeout",
        str(timeout),
    ]
    if market:
        cmd += ["--market", market]
    if timeframe:
        cmd += ["--timeframe", timeframe]
    if provider:
        cmd += ["--provider", provider]
    if initial_equity is not None:
        cmd += ["--initial-equity", str(initial_equity)]
    if notional is not None:
        cmd += ["--notional", str(notional)]
    code, payload = _run_json(cmd, timeout=(timeout + 10) * len(strategies))
    return {"exit_code": code, **payload}


def _context_pack(
    *,
    symbol: str,
    market: str,
    timeframe: str,
    provider: str,
    include_news: bool = False,
    news_limit: int = 5,
    news_since_minutes: int = 240,
) -> dict[str, Any]:
    context: dict[str, Any] = {"quotes": None, "indicators": None, "warnings": []}
    market_hint = market
    provider_hint = provider
    if not market_hint and ("_" in symbol or symbol.upper().endswith("USDT")):
        market_hint = "crypto_spot"
    if not provider_hint and market_hint in {"crypto", "crypto_spot"}:
        provider_hint = "gate"

    quote_cmd = [sys.executable, str(QUOTES_SCRIPT), "--symbols", symbol, "--timeout", "12"]
    if market_hint:
        quote_cmd += ["--market", market_hint]
    if provider_hint:
        quote_cmd += ["--provider", provider_hint]
    quote_code, quote_payload = _run_json(quote_cmd, timeout=30)
    if quote_code == 0 and quote_payload.get("ok"):
        context["quotes"] = quote_payload
    else:
        context["warnings"].append({"source": "quotes", "payload": quote_payload})

    indicator_cmd = [
        sys.executable,
        str(INDICATORS_SCRIPT),
        "--symbol",
        symbol,
        "--indicator",
        "rsi,ema,macd",
        "--limit",
        "120",
    ]
    if market_hint:
        indicator_cmd += ["--market", market_hint]
    if provider_hint:
        indicator_cmd += ["--provider", provider_hint]
    if timeframe:
        indicator_cmd += ["--timeframe", timeframe]
    indicator_code, indicator_payload = _run_json(indicator_cmd, timeout=45)
    if indicator_code == 0 and indicator_payload.get("ok"):
        context["indicators"] = indicator_payload
    else:
        context["warnings"].append({"source": "indicators", "payload": indicator_payload})
    if include_news:
        news_payload = _news_context(symbol, limit=news_limit, since_minutes=news_since_minutes)
        if news_payload.get("ok"):
            context["news"] = news_payload
            context["news_feedback"] = _summarize_news_context(news_payload)
        else:
            context["warnings"].append({"source": "news", "payload": news_payload})
    return context


def _normalize_watchlist(raw: str) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for item in (raw or "").split(","):
        symbol = item.strip()
        if not symbol:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", symbol):
            raise ValueError(f"Invalid watchlist symbol: {symbol}")
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def _metric_optional(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_watchlist_quotes(
    *,
    watchlist: list[str],
    market: str,
    provider: str,
) -> dict[str, Any] | None:
    if not watchlist:
        return None
    market_hint = market
    provider_hint = provider
    if not market_hint and all("_" in symbol or symbol.upper().endswith("USDT") for symbol in watchlist):
        market_hint = "crypto_spot"
    if not provider_hint and market_hint in {"crypto", "crypto_spot"}:
        provider_hint = "gate"

    cmd = [sys.executable, str(QUOTES_SCRIPT), "--symbols", ",".join(watchlist), "--timeout", "12"]
    if market_hint:
        cmd += ["--market", market_hint]
    if provider_hint:
        cmd += ["--provider", provider_hint]
    _, payload = _run_json(cmd, timeout=45)
    return payload


def _build_watchlist_ranking(
    *,
    watchlist: list[str],
    target_symbol: str,
    context: dict[str, Any],
    market: str,
    provider: str,
) -> list[dict[str, Any]]:
    if not watchlist:
        return []

    quote_payload = _fetch_watchlist_quotes(watchlist=watchlist, market=market, provider=provider)
    quote_by_symbol: dict[str, dict[str, Any]] = {}
    if quote_payload and isinstance(quote_payload.get("data"), list):
        for item in quote_payload["data"]:
            if not isinstance(item, dict):
                continue
            raw_symbol = item.get("request_symbol") or item.get("symbol")
            normalized = item.get("symbol")
            if raw_symbol:
                quote_by_symbol[str(raw_symbol)] = item
            if normalized:
                quote_by_symbol[str(normalized)] = item

    target_indicators_available = bool(((context.get("indicators") or {}).get("data") or {}).get("indicators"))
    ranked: list[dict[str, Any]] = []
    for index, symbol in enumerate(watchlist):
        quote = quote_by_symbol.get(symbol) or {}
        quote_ok = bool(quote.get("ok"))
        amount = _metric_optional(quote.get("amount"))
        volume = _metric_optional(quote.get("volume"))
        liquidity_score = amount if amount is not None else (volume if volume is not None else 0.0)
        indicator_available = target_indicators_available if symbol == target_symbol else None
        score = 0.0
        reasons: list[str] = []
        if quote_ok:
            score += 10.0
            reasons.append("quote available")
        else:
            reasons.append("quote unavailable")
        if liquidity_score > 0:
            score += min(10.0, liquidity_score / 1_000_000)
            reasons.append("liquidity visible")
        if symbol == target_symbol:
            score += 5.0
            reasons.append("target symbol")
            if indicator_available:
                score += 3.0
                reasons.append("indicators available")
            else:
                reasons.append("indicators unavailable")

        ranked.append(
            {
                "symbol": symbol,
                "rank": 0,
                "score": round(score, 6),
                "quote_ok": quote_ok,
                "indicator_available": indicator_available,
                "amount": amount,
                "volume": volume,
                "reason": ", ".join(reasons),
                "source": "user_watchlist",
                "input_order": index,
            }
        )

    ranked.sort(key=lambda item: (item["score"], item["input_order"] == 0, -item["input_order"]), reverse=True)
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    return ranked


def _promotion_gate(
    *,
    mode: str,
    winner: str | None,
    compare_result: dict[str, Any],
    candidate_results: list[dict[str, Any]],
) -> dict[str, Any]:
    gate_reasons: list[str] = []
    passed: dict[str, bool] = {
        "candidate_selected": False,
        "candidate_beats_baseline": False,
        "candidate_has_enough_trades": False,
        "candidate_does_not_overtrade": False,
        "candidate_has_explainable_changes": False,
        "candidate_written_and_validated": False,
        "paper_mode_enabled": mode == "paper",
    }
    details: dict[str, Any] = {
        "winner": winner,
        "min_trades": 1,
        "max_signals_total": 80,
    }

    ranking = ((compare_result.get("data") or {}).get("ranking") or []) if compare_result.get("ok") else []
    winner_item = next((item for item in ranking if item.get("strategy") == winner), None) if winner else None
    candidate_meta = next((item for item in candidate_results if item.get("strategy") == winner), None) if winner else None

    if winner and winner_item:
        passed["candidate_selected"] = True
    else:
        gate_reasons.append("no winner selected")

    if winner_item:
        score_parts = winner_item.get("score_parts") or {}
        baseline_delta = _metric_optional(winner_item.get("baseline_delta"))
        if baseline_delta is None:
            baseline_delta = _metric_optional(score_parts.get("baseline_delta"))
        trades = int(_metric_optional(winner_item.get("trades")) or _metric_optional(score_parts.get("trade_count")) or 0)
        signals_total = int(
            _metric_optional(winner_item.get("signals_total")) or _metric_optional(score_parts.get("signals_total")) or 0
        )
        details.update(
            {
                "baseline_delta": baseline_delta,
                "trades": trades,
                "signals_total": signals_total,
                "candidate_gate": winner_item.get("gate"),
            }
        )

        if baseline_delta is not None and baseline_delta > 0:
            passed["candidate_beats_baseline"] = True
        else:
            gate_reasons.append("candidate did not beat baseline")
        if trades >= details["min_trades"]:
            passed["candidate_has_enough_trades"] = True
        else:
            gate_reasons.append("candidate has too few trades")
        if 0 < signals_total <= details["max_signals_total"]:
            passed["candidate_does_not_overtrade"] = True
        else:
            gate_reasons.append("candidate signal count outside gate")
    elif winner:
        gate_reasons.append("winner missing from ranking")

    if candidate_meta and candidate_meta.get("hypothesis") and candidate_meta.get("changes"):
        passed["candidate_has_explainable_changes"] = True
    else:
        gate_reasons.append("candidate lacks explainable changes")

    validation = (candidate_meta or {}).get("validation") or {}
    if candidate_meta and validation.get("ok") and validation.get("data", {}).get("written"):
        passed["candidate_written_and_validated"] = True
    else:
        gate_reasons.append("candidate was not written and validated")

    if mode != "paper":
        gate_reasons.append("paper mode not enabled")

    eligible = all(passed.values())
    return {
        "eligible": eligible,
        "activated": False,
        "gate_passed": eligible,
        "gates": passed,
        "gate_reasons": gate_reasons,
        "details": details,
        "reason": "promotion gate passed; paper activation not implemented in E5-P1"
        if eligible
        else "; ".join(gate_reasons),
    }


def _split_rejected_reasons(raw: str) -> list[str]:
    if not raw:
        return []
    reasons = []
    for item in re.split(r"[,;\n]+", raw):
        reason = item.strip()
        if reason:
            reasons.append(reason)
    return reasons


def _load_previous_repair_guidance(raw: str) -> list[str]:
    value = (raw or "").strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return _dedupe_strings([str(item) for item in parsed])
    if isinstance(parsed, dict):
        source = parsed.get("repair_guidance") or parsed.get("items") or parsed.get("repair_hints") or []
        if isinstance(source, list):
            return _dedupe_strings([str(item) for item in source])
        if isinstance(source, str):
            return _split_rejected_reasons(source)
    return _split_rejected_reasons(value)


def _load_json_object_arg(raw: str, *, label: str) -> dict[str, Any] | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        parse_error = e
    else:
        if not isinstance(parsed, dict):
            raise ValueError(f"{label} must be a JSON object")
        return parsed

    path = Path(value)
    try:
        is_file = path.is_file()
    except OSError as e:
        raise ValueError(f"{label} is not valid JSON or a file path: {parse_error}") from e
    if not is_file:
        raise ValueError(f"{label} is not valid JSON or a file path: {parse_error}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{label} file is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} file must be a JSON object")
    return parsed


def _load_previous_paper_report(raw: str) -> dict[str, Any] | None:
    return _load_json_object_arg(raw, label="previous paper report")


def _load_previous_risk_summary(raw: str) -> dict[str, Any] | None:
    return _load_json_object_arg(raw, label="previous risk summary")


def _current_target() -> str | None:
    current = STRATEGIES_ROOT / "current"
    if current.is_symlink():
        return str(current.resolve(strict=False))
    if current.exists():
        return str(current.resolve(strict=False))
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4 MVP strategy dry-run loop.")
    parser.add_argument("--strategy", default="current/fast_1m.yaml", help="Baseline strategy")
    parser.add_argument("--symbol", required=True, help="Target symbol, e.g. BTC_USDT")
    parser.add_argument("--watchlist", default="", help="Comma-separated watchlist; target symbol must be included when provided")
    parser.add_argument("--market", default="", help="Optional market hint")
    parser.add_argument("--days", type=int, default=7, help="Backtest lookback days")
    parser.add_argument("--timeframe", default="", help="Optional timeframe override")
    parser.add_argument("--provider", default="", help="Optional provider override")
    parser.add_argument("--min-strength", type=int, default=50, help="Min signal strength")
    parser.add_argument("--initial-equity", type=float, default=None, help="Optional paper initial equity")
    parser.add_argument("--notional", type=float, default=None, help="Optional paper notional")
    parser.add_argument("--candidate-count", type=int, default=2, help="Candidate count, 2-3 for MVP")
    parser.add_argument(
        "--agent-candidates",
        default="",
        help="Optional Agent-authored candidate JSON string or file. The system still validates, writes, backtests, and gates candidates.",
    )
    parser.add_argument(
        "--agent-generator-mode",
        choices=["off", "file"],
        default="off",
        help="Explicit Agent/LLM generator adapter mode. Default off; file reads --agent-generator-output JSON only.",
    )
    parser.add_argument(
        "--agent-generator-output",
        default="",
        help="JSON file produced by an external Agent/LLM generator when --agent-generator-mode=file.",
    )
    parser.add_argument("--previous-rejected-reasons", default="", help="Optional previous loop rejected reasons")
    parser.add_argument("--previous-paper-report", default="", help="Optional previous paper report JSON object or file path")
    parser.add_argument("--previous-risk-summary", default="", help="Optional previous risk summary JSON object or file path")
    parser.add_argument("--previous-repair-guidance", default="", help="Optional previous repair guidance JSON list/object or delimited string")
    parser.add_argument("--include-news", action="store_true", help="Optionally include read-only news context")
    parser.add_argument("--news-limit", type=int, default=5, help="Max news articles when --include-news is used")
    parser.add_argument("--news-since-minutes", type=int, default=240, help="News lookback minutes when --include-news is used")
    parser.add_argument("--run-id", default="", help="Optional fixed run id for reproducible dry-runs")
    parser.add_argument("--keep-candidates", action="store_true", help="Keep generated config/strategies/agent_*.yaml files")
    parser.add_argument("--cleanup-old-candidates", action="store_true", help="Delete old config/strategies/agent_*.yaml files after the run")
    parser.add_argument("--keep-last-runs", type=int, default=10, help="When cleaning, keep this many newest agent candidate YAML files")
    parser.add_argument("--mode", choices=["suggest", "dry_run", "paper"], default="dry_run", help="Loop mode; paper is reserved")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-backtest timeout seconds")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    response = _base_response()
    try:
        watchlist = _normalize_watchlist(args.watchlist)
    except ValueError as e:
        response["error"] = _error_payload("invalid_watchlist", str(e))
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    previous_rejected_reasons = _split_rejected_reasons(args.previous_rejected_reasons)
    previous_repair_guidance = _load_previous_repair_guidance(args.previous_repair_guidance)
    if args.agent_candidates and args.agent_generator_mode != "off":
        response["error"] = _error_payload("invalid_arguments", "--agent-candidates cannot be combined with --agent-generator-mode")
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.agent_generator_output and args.agent_generator_mode == "off":
        response["error"] = _error_payload("invalid_arguments", "--agent-generator-output requires --agent-generator-mode=file")
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.agent_generator_mode == "file" and args.mode == "paper":
        response["error"] = _error_payload("invalid_arguments", "--agent-generator-mode=file is limited to suggest/dry_run")
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    try:
        previous_paper_report = _load_previous_paper_report(args.previous_paper_report)
    except ValueError as e:
        response["error"] = _error_payload("invalid_previous_paper_report", str(e))
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    try:
        previous_risk_summary = _load_previous_risk_summary(args.previous_risk_summary)
    except ValueError as e:
        response["error"] = _error_payload("invalid_previous_risk_summary", str(e))
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    try:
        agent_candidate_drafts = _load_agent_candidate_drafts(args.agent_candidates)
    except (json.JSONDecodeError, ValueError) as e:
        response["error"] = _error_payload("invalid_agent_candidates", str(e))
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    cleanup_result: dict[str, Any] = {
        "enabled": False,
        "keep_last_runs": args.keep_last_runs,
        "kept": [],
        "deleted": [],
        "skipped": [],
    }
    try:
        run_id = _safe_run_id(args.run_id, args.symbol)
    except ValueError as e:
        response["error"] = _error_payload("invalid_run_id", str(e))
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    artifact_dir = _init_artifact_dir(run_id)
    agent_generator_path: Path | None = None
    agent_generator: dict[str, Any] | None = None
    generator_source = "agent_draft" if agent_candidate_drafts else "deterministic"
    if args.agent_generator_mode == "file":
        try:
            agent_generator, agent_candidate_drafts = _load_agent_generator_file(args.agent_generator_output)
        except (json.JSONDecodeError, ValueError) as e:
            response["error"] = _error_payload("invalid_agent_generator_output", str(e))
            json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
            sys.stdout.write("\n")
            return 1
        generator_source = "agent_generator_file"
        agent_generator_path = artifact_dir / "agent_generator.json"
        _write_json(agent_generator_path, agent_generator)
    response["request"] = {
        "strategy": args.strategy,
        "symbol": args.symbol,
        "watchlist": watchlist,
        "market": args.market or None,
        "days": args.days,
        "timeframe": args.timeframe or None,
        "provider": args.provider or None,
        "min_strength": args.min_strength,
        "candidate_count": args.candidate_count,
        "generator_source": generator_source,
        "agent_generator": {
            "mode": args.agent_generator_mode,
            "enabled": args.agent_generator_mode != "off",
            "output": args.agent_generator_output or None,
        },
        "agent_candidate_count": len(agent_candidate_drafts or []),
        "previous_rejected_reasons": previous_rejected_reasons,
        "previous_paper_report": bool(previous_paper_report),
        "previous_risk_summary": bool(previous_risk_summary),
        "previous_repair_guidance": previous_repair_guidance,
        "include_news": bool(args.include_news),
        "news_limit": args.news_limit,
        "news_since_minutes": args.news_since_minutes,
        "run_id": run_id,
        "keep_candidates": bool(args.keep_candidates) or not args.cleanup_old_candidates,
        "cleanup_old_candidates": bool(args.cleanup_old_candidates),
        "keep_last_runs": args.keep_last_runs,
        "mode": args.mode,
    }
    goal_payload = {
        "run_id": run_id,
        "created_at": response["ts"],
        "request": response["request"],
        "objective": "E4 dry-run strategy generation and validation loop",
        "non_goals": [
            "no live trading",
            "no automatic current activation",
            "no full-market stock selection",
            "news is not required",
        ],
    }

    if args.keep_candidates and args.cleanup_old_candidates:
        response["error"] = _error_payload("invalid_arguments", "--keep-candidates and --cleanup-old-candidates are mutually exclusive")
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            decision={"ok": False, "error": response["error"], "promotion": {"activated": False}},
        )
        response["data"] = {"run_id": run_id, **artifact}
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.keep_last_runs < 0:
        response["error"] = _error_payload("invalid_arguments", "--keep-last-runs must be >= 0")
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            decision={"ok": False, "error": response["error"], "promotion": {"activated": False}},
        )
        response["data"] = {"run_id": run_id, **artifact}
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.days <= 0:
        response["error"] = _error_payload("invalid_arguments", "--days must be > 0")
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            decision={"ok": False, "error": response["error"], "promotion": {"activated": False}},
        )
        response["data"] = {"run_id": run_id, **artifact}
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.news_limit <= 0:
        response["error"] = _error_payload("invalid_arguments", "--news-limit must be > 0")
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            decision={"ok": False, "error": response["error"], "promotion": {"activated": False}},
        )
        response["data"] = {"run_id": run_id, **artifact}
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if args.news_since_minutes <= 0:
        response["error"] = _error_payload("invalid_arguments", "--news-since-minutes must be > 0")
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            decision={"ok": False, "error": response["error"], "promotion": {"activated": False}},
        )
        response["data"] = {"run_id": run_id, **artifact}
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if watchlist and args.symbol not in watchlist:
        response["error"] = _error_payload("symbol_not_in_watchlist", "Target symbol must be included in watchlist")
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            decision={"ok": False, "error": response["error"], "promotion": {"activated": False}},
        )
        response["data"] = {"run_id": run_id, **artifact}
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1

    current_before = _current_target()
    try:
        _, baseline_data = _read_strategy(args.strategy)
    except Exception as e:  # noqa: BLE001
        response["error"] = _error_payload("baseline_read_failed", str(e))
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            decision={"ok": False, "error": response["error"], "promotion": {"activated": False}},
        )
        response["data"] = {"run_id": run_id, **artifact}
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    context = _context_pack(
        symbol=args.symbol,
        market=args.market,
        timeframe=args.timeframe,
        provider=args.provider,
        include_news=bool(args.include_news),
        news_limit=max(1, min(20, int(args.news_limit))),
        news_since_minutes=max(1, int(args.news_since_minutes)),
    )
    if previous_paper_report:
        context["previous_paper_report"] = previous_paper_report
        context["previous_paper_feedback"] = _summarize_paper_report(previous_paper_report)
    if previous_risk_summary:
        context["previous_risk_summary"] = previous_risk_summary
        context["previous_risk_feedback"] = _summarize_risk_summary(previous_risk_summary)
    if previous_repair_guidance:
        context["previous_repair_guidance"] = previous_repair_guidance
        context["previous_repair_feedback"] = _summarize_repair_guidance(previous_repair_guidance)
    watchlist_ranking = _build_watchlist_ranking(
        watchlist=watchlist or [args.symbol],
        target_symbol=args.symbol,
        context=context,
        market=args.market,
        provider=args.provider,
    )
    context["watchlist_ranking"] = watchlist_ranking
    requested_candidate_count = max(2, min(5, int(args.candidate_count)))
    agent_prompt_pack = _build_agent_prompt_pack(
        run_id=run_id,
        strategy=args.strategy,
        baseline=baseline_data,
        symbol=args.symbol,
        watchlist=watchlist or [args.symbol],
        context=context,
        candidate_count=requested_candidate_count,
        previous_rejected_reasons=previous_rejected_reasons,
    )
    agent_prompt_path = artifact_dir / "agent_prompt.json"
    _write_json(agent_prompt_path, agent_prompt_pack)
    agent_feedback_path = artifact_dir / "agent_feedback.json"
    _write_json(agent_feedback_path, agent_prompt_pack["agent_feedback"])
    agent_response_template_path = artifact_dir / "agent_response_template.json"
    _write_json(
        agent_response_template_path,
        _agent_response_template(symbol=args.symbol, candidate_count=requested_candidate_count),
    )
    agent_response_path: Path | None = None
    agent_response_validation_path: Path | None = None
    agent_response_validation: dict[str, Any] | None = None
    agent_handoff_path: Path | None = None
    context_health = agent_prompt_pack["context_health"]
    agent_next_action: dict[str, Any] | None = None
    agent_submission: dict[str, Any] | None = None

    def write_agent_handoff(status: str) -> Path:
        nonlocal agent_handoff_path, agent_next_action, agent_submission
        repair_guidance = (agent_response_validation or {}).get("repair_guidance") or []
        agent_next_action = _agent_next_action(
            status=status,
            context_health=context_health,
            repair_guidance=repair_guidance,
            agent_feedback=agent_prompt_pack["agent_feedback"],
        )
        agent_submission = _agent_submission_hint(
            strategy=args.strategy,
            symbol=args.symbol,
            watchlist=watchlist or [args.symbol],
            market=args.market,
            days=args.days,
            timeframe=args.timeframe,
            provider=args.provider,
            min_strength=args.min_strength,
            initial_equity=args.initial_equity,
            notional=args.notional,
            mode=args.mode,
            candidate_count=requested_candidate_count,
            include_news=bool(args.include_news),
            news_limit=args.news_limit,
            news_since_minutes=args.news_since_minutes,
            timeout=args.timeout,
            agent_next_action=agent_next_action,
        )
        agent_handoff_path = _write_agent_handoff_artifact(
            artifact_dir=artifact_dir,
            run_id=run_id,
            mode=args.mode,
            strategy=args.strategy,
            symbol=args.symbol,
            watchlist=watchlist or [args.symbol],
            generator_source=response["request"]["generator_source"],
            candidate_count=requested_candidate_count,
            status=status,
            agent_prompt_path=agent_prompt_path,
            agent_feedback_path=agent_feedback_path,
            agent_response_template_path=agent_response_template_path,
            agent_response_path=agent_response_path,
            agent_response_validation_path=agent_response_validation_path,
            agent_feedback=agent_prompt_pack["agent_feedback"],
            context_health=context_health,
            agent_next_action=agent_next_action,
            agent_submission=agent_submission,
            repair_guidance=repair_guidance,
        )
        return agent_handoff_path

    if agent_candidate_drafts:
        candidate_count = max(2, min(5, requested_candidate_count, len(agent_candidate_drafts)))
        selected_agent_drafts = agent_candidate_drafts[:candidate_count]
        try:
            candidates = _agent_drafts_to_candidates(
                drafts=selected_agent_drafts,
                symbol=args.symbol,
                run_id=run_id,
                generator_source=generator_source,
                context=context,
                previous_rejected_reasons=previous_rejected_reasons,
            )
        except (yaml.YAMLError, ValueError) as e:
            response["error"] = _error_payload("invalid_agent_candidates", str(e))
            agent_response_path = artifact_dir / "agent_response.json"
            _write_json(
                agent_response_path,
                _agent_response_audit(
                    drafts=selected_agent_drafts,
                    candidates=None,
                    symbol=args.symbol,
                    status="rejected",
                    source=generator_source,
                    error=response["error"],
                ),
            )
            agent_response_validation_path = artifact_dir / "agent_response_validation.json"
            agent_response_validation = _agent_response_validation_report(
                drafts=selected_agent_drafts,
                candidates=None,
                symbol=args.symbol,
                status="rejected",
                source=generator_source,
                error=response["error"],
            )
            _write_json(agent_response_validation_path, agent_response_validation)
            write_agent_handoff("agent_draft_rejected")
            artifact = _finalize_artifacts(
                artifact_dir=artifact_dir,
                goal=goal_payload,
                context=context,
                decision={"ok": False, "error": response["error"], "promotion": {"activated": False}},
            )
            response["data"] = {
                "run_id": run_id,
                **artifact,
                "agent_prompt": _artifact_rel(agent_prompt_path),
                "agent_feedback": _artifact_rel(agent_feedback_path),
                "agent_handoff": _artifact_rel(agent_handoff_path) if agent_handoff_path else None,
                "agent_response_template": _artifact_rel(agent_response_template_path),
                "agent_response": _artifact_rel(agent_response_path) if agent_response_path else None,
                "agent_response_validation": _artifact_rel(agent_response_validation_path) if agent_response_validation_path else None,
                "agent_generator": _artifact_rel(agent_generator_path) if agent_generator_path else None,
                "agent_repair_guidance": (agent_response_validation or {}).get("repair_guidance") or [],
                "context_health": context_health,
                "agent_next_action": agent_next_action,
                "agent_submission": agent_submission,
            }
            json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
            sys.stdout.write("\n")
            return 1
        agent_response_path = artifact_dir / "agent_response.json"
        _write_json(
            agent_response_path,
            _agent_response_audit(
                drafts=selected_agent_drafts,
                candidates=candidates,
                symbol=args.symbol,
                status="accepted_for_validation",
                source=generator_source,
            ),
        )
    else:
        candidate_count = max(2, min(3, int(args.candidate_count)))
        candidates = _generate_candidates(
            baseline=baseline_data,
            symbol=args.symbol,
            run_id=run_id,
            count=candidate_count,
            context=context,
            previous_rejected_reasons=previous_rejected_reasons,
        )
    candidates = _static_sanity_check_candidates(candidates, symbol=args.symbol)
    if agent_candidate_drafts:
        agent_response_validation_path = artifact_dir / "agent_response_validation.json"
        static_failed = any(not (candidate.get("static_sanity") or {}).get("ok") for candidate in candidates)
        agent_response_validation = _agent_response_validation_report(
            drafts=selected_agent_drafts,
            candidates=candidates,
            symbol=args.symbol,
            status="failed" if static_failed else "passed",
            source=generator_source,
        )
        _write_json(agent_response_validation_path, agent_response_validation)
    sanity_failures = [
        {
            "strategy": candidate["strategy"],
            "errors": (candidate.get("static_sanity") or {}).get("errors") or [],
            "warnings": (candidate.get("static_sanity") or {}).get("warnings") or [],
        }
        for candidate in candidates
        if not (candidate.get("static_sanity") or {}).get("ok")
    ]
    if sanity_failures:
        promotion = {
            "eligible": False,
            "activated": False,
            "gate_passed": False,
            "gates": {
                "candidate_selected": False,
                "candidate_beats_baseline": False,
                "candidate_has_enough_trades": False,
                "candidate_does_not_overtrade": False,
                "candidate_has_explainable_changes": False,
                "candidate_written_and_validated": False,
                "paper_mode_enabled": args.mode == "paper",
            },
            "gate_reasons": ["candidate static sanity failed"],
            "reason": "candidate static sanity failed",
        }
        response["error"] = _error_payload(
            "candidate_static_sanity_failed",
            "Candidate failed static sanity checks",
            {"failures": sanity_failures},
        )
        decision = {
            "ok": False,
            "mode": args.mode,
            "winner": None,
            "error": response["error"],
            "watchlist_ranking": watchlist_ranking,
            "promotion": promotion,
            "candidate_retention": cleanup_result,
            "current_changed": current_before != _current_target(),
        }
        write_agent_handoff("candidate_static_sanity_failed")
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            context=context,
            candidate_results=[{k: v for k, v in candidate.items() if k != "content"} for candidate in candidates],
            decision=decision,
        )
        response["data"] = {
            "mode": args.mode,
            "run_id": run_id,
            **artifact,
            "agent_prompt": _artifact_rel(agent_prompt_path),
            "agent_feedback": _artifact_rel(agent_feedback_path),
            "agent_handoff": _artifact_rel(agent_handoff_path) if agent_handoff_path else None,
            "agent_response_template": _artifact_rel(agent_response_template_path),
            "agent_response": _artifact_rel(agent_response_path) if agent_response_path else None,
            "agent_response_validation": _artifact_rel(agent_response_validation_path) if agent_response_validation_path else None,
            "agent_generator": _artifact_rel(agent_generator_path) if agent_generator_path else None,
            "agent_repair_guidance": (agent_response_validation or {}).get("repair_guidance") or [],
            "context_health": context_health,
            "agent_next_action": agent_next_action,
            "agent_submission": agent_submission,
            "baseline": args.strategy,
            "context": context,
            "watchlist_ranking": watchlist_ranking,
            "candidates": [{k: v for k, v in candidate.items() if k != "content"} for candidate in candidates],
            "promotion": promotion,
            "candidate_retention": cleanup_result,
            "current_before": current_before,
            "current_after": _current_target(),
            "current_changed": current_before != _current_target(),
        }
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    candidate_artifacts = _write_candidate_artifacts(artifact_dir, candidates)

    if args.mode == "suggest":
        decision = {
            "ok": True,
            "mode": "suggest",
            "winner": None,
            "watchlist_ranking": watchlist_ranking,
            "promotion": {
                "eligible": False,
                "activated": False,
                "gate_passed": False,
                "gates": {
                    "candidate_selected": False,
                    "candidate_beats_baseline": False,
                    "candidate_has_enough_trades": False,
                    "candidate_does_not_overtrade": False,
                    "candidate_has_explainable_changes": False,
                    "candidate_written_and_validated": False,
                    "paper_mode_enabled": False,
                },
                "gate_reasons": ["suggest mode does not run promotion gate"],
                "reason": "suggest mode",
            },
            "candidate_retention": cleanup_result,
            "current_changed": current_before != _current_target(),
        }
        write_agent_handoff("suggest_ready")
        artifact = _finalize_artifacts(
            artifact_dir=artifact_dir,
            goal=goal_payload,
            context=context,
            candidate_results=[
                {
                    **{k: v for k, v in candidate.items() if k != "content"},
                    "artifact_path": candidate_artifacts[idx].get("path") if idx < len(candidate_artifacts) else None,
                }
                for idx, candidate in enumerate(candidates)
            ],
            decision=decision,
        )
        response["ok"] = True
        response["data"] = {
            "mode": "suggest",
            "run_id": run_id,
            **artifact,
            "agent_prompt": _artifact_rel(agent_prompt_path),
            "agent_feedback": _artifact_rel(agent_feedback_path),
            "agent_handoff": _artifact_rel(agent_handoff_path) if agent_handoff_path else None,
            "agent_response_template": _artifact_rel(agent_response_template_path),
            "agent_response": _artifact_rel(agent_response_path) if agent_response_path else None,
            "agent_response_validation": _artifact_rel(agent_response_validation_path) if agent_response_validation_path else None,
            "agent_generator": _artifact_rel(agent_generator_path) if agent_generator_path else None,
            "agent_repair_guidance": (agent_response_validation or {}).get("repair_guidance") or [],
            "context_health": context_health,
            "agent_next_action": agent_next_action,
            "agent_submission": agent_submission,
            "baseline": args.strategy,
            "context": context,
            "watchlist_ranking": watchlist_ranking,
            "candidates": [
                {
                    **{k: v for k, v in candidate.items() if k != "content"},
                    "artifact_path": candidate_artifacts[idx].get("path") if idx < len(candidate_artifacts) else None,
                }
                for idx, candidate in enumerate(candidates)
            ],
            "promotion": decision["promotion"],
            "candidate_retention": cleanup_result,
            "current_before": current_before,
            "current_after": _current_target(),
            "current_changed": current_before != _current_target(),
        }
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 0

    write_results: list[dict[str, Any]] = []
    for candidate in candidates:
        result = _manage_write(
            candidate,
            note=f"E4 dry_run candidate {run_id}: {candidate['hypothesis']}",
        )
        write_results.append(
            {
                "strategy": candidate["strategy"],
                "hypothesis": candidate["hypothesis"],
                "changes": candidate["changes"],
                "generator_context": candidate.get("generator_context") or {},
                "static_sanity": candidate.get("static_sanity") or {},
                "validation": result,
            }
        )
        if not result.get("ok"):
            promotion = {
                "eligible": False,
                "activated": False,
                "gate_passed": False,
                "gates": {
                    "candidate_selected": False,
                    "candidate_beats_baseline": False,
                    "candidate_has_enough_trades": False,
                    "candidate_does_not_overtrade": False,
                    "candidate_has_explainable_changes": False,
                    "candidate_written_and_validated": False,
                    "paper_mode_enabled": args.mode == "paper",
                },
                "gate_reasons": ["candidate write failed"],
                "reason": "candidate write failed",
            }
            response["error"] = _error_payload(
                "candidate_write_failed",
                f"Candidate failed validation/write: {candidate['strategy']}",
                {"candidate": candidate["strategy"], "result": result},
            )
            decision = {
                "ok": False,
                "mode": args.mode,
                "winner": None,
                "error": response["error"],
                "watchlist_ranking": watchlist_ranking,
                "promotion": promotion,
                "candidate_retention": cleanup_result,
                "current_changed": current_before != _current_target(),
            }
            write_agent_handoff("candidate_write_failed")
            artifact = _finalize_artifacts(
                artifact_dir=artifact_dir,
                goal=goal_payload,
                context=context,
                candidate_results=write_results,
                decision=decision,
            )
            response["data"] = {
                "mode": args.mode,
                "run_id": run_id,
                **artifact,
                "agent_prompt": _artifact_rel(agent_prompt_path),
                "agent_feedback": _artifact_rel(agent_feedback_path),
                "agent_handoff": _artifact_rel(agent_handoff_path) if agent_handoff_path else None,
                "agent_response_template": _artifact_rel(agent_response_template_path),
                "agent_response": _artifact_rel(agent_response_path) if agent_response_path else None,
                "agent_response_validation": _artifact_rel(agent_response_validation_path) if agent_response_validation_path else None,
                "agent_generator": _artifact_rel(agent_generator_path) if agent_generator_path else None,
                "agent_repair_guidance": (agent_response_validation or {}).get("repair_guidance") or [],
                "context_health": context_health,
                "agent_next_action": agent_next_action,
                "agent_submission": agent_submission,
                "baseline": args.strategy,
                "context": context,
                "watchlist_ranking": watchlist_ranking,
                "candidates": write_results,
                "promotion": promotion,
                "candidate_retention": cleanup_result,
                "current_before": current_before,
                "current_after": _current_target(),
                "current_changed": current_before != _current_target(),
            }
            json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
            sys.stdout.write("\n")
            return 1

    strategy_names = [args.strategy] + [candidate["strategy"] for candidate in candidates]
    compare_result = _compare(
        strategies=strategy_names,
        symbol=args.symbol,
        market=args.market,
        days=args.days,
        timeframe=args.timeframe,
        provider=args.provider,
        min_strength=args.min_strength,
        initial_equity=args.initial_equity,
        notional=args.notional,
        timeout=args.timeout,
    )
    winner = ((compare_result.get("data") or {}).get("winner") if compare_result.get("ok") else None)
    if args.cleanup_old_candidates:
        cleanup_result = _cleanup_old_candidates(keep_last_runs=args.keep_last_runs)
    promotion = _promotion_gate(
        mode=args.mode,
        winner=winner,
        compare_result=compare_result,
        candidate_results=write_results,
    )
    activation_result: dict[str, Any] | None = None
    paper_activation_failed = False
    paper_report: dict[str, Any] | None = None
    if args.mode == "paper":
        if not promotion.get("eligible"):
            activation_result = {
                "ok": False,
                "skipped": True,
                "reason": "promotion gate failed",
                "gate_reasons": promotion.get("gate_reasons") or [],
            }
        elif not winner:
            activation_result = {"ok": False, "skipped": True, "reason": "winner missing"}
            promotion["eligible"] = False
            promotion["gate_passed"] = False
            promotion.setdefault("gate_reasons", []).append("winner missing")
            promotion["reason"] = "; ".join(promotion["gate_reasons"])
        else:
            activation_result = _manage_use(
                winner,
                note=f"E5 paper promotion {run_id}: {winner}",
            )
            if activation_result.get("ok"):
                promotion["activated"] = True
                promotion["activation"] = activation_result.get("data")
                promotion["release_id"] = (activation_result.get("data") or {}).get("release_id")
                paper_report = _paper_report(args.symbol)
                promotion["paper_report_ok"] = bool(paper_report.get("ok"))
                if paper_report.get("ok"):
                    context["paper_report"] = paper_report
                else:
                    context.setdefault("warnings", []).append({"source": "paper_report", "payload": paper_report})
            else:
                promotion["activated"] = False
                promotion["activation_failed"] = True
                promotion["activation_error"] = activation_result.get("error")
                promotion["reason"] = "promotion gate passed but strategy activation failed"
                paper_activation_failed = True
    current_after = _current_target()
    current_changed = current_before != current_after
    paper_gate_failed = args.mode == "paper" and not promotion.get("eligible")
    decision = {
        "ok": bool(compare_result.get("ok"))
        and (
            (args.mode == "dry_run" and not current_changed)
            or (args.mode == "paper" and bool(promotion.get("activated")))
        ),
        "mode": args.mode,
        "winner": winner,
        "rejected_reasons": (compare_result.get("data") or {}).get("rejected_reasons"),
        "portfolio_risk_summary": (compare_result.get("data") or {}).get("portfolio_risk_summary"),
        "watchlist_ranking": watchlist_ranking,
        "next_step": (
            f"Paper activated {winner}; monitor paper report."
            if args.mode == "paper" and promotion.get("activated")
            else (
                f"Review {winner}; dry_run did not activate current."
                if winner and args.mode == "dry_run"
                else "No candidate passed gates; keep baseline and generate another batch."
            )
        ),
        "promotion": promotion,
        "activation_result": activation_result,
        "paper_report": paper_report,
        "candidate_retention": cleanup_result,
        "current_before": current_before,
        "current_after": current_after,
        "current_changed": current_changed,
    }
    write_agent_handoff("comparison_complete")
    artifact = _finalize_artifacts(
        artifact_dir=artifact_dir,
        goal=goal_payload,
        context=context,
        candidate_results=write_results,
        compare_result=compare_result,
        decision=decision,
    )
    response["ok"] = bool(compare_result.get("ok"))
    response["data"] = {
        "mode": args.mode,
        "run_id": run_id,
        **artifact,
        "agent_prompt": _artifact_rel(agent_prompt_path),
        "agent_feedback": _artifact_rel(agent_feedback_path),
        "agent_handoff": _artifact_rel(agent_handoff_path) if agent_handoff_path else None,
        "agent_response_template": _artifact_rel(agent_response_template_path),
        "agent_response": _artifact_rel(agent_response_path) if agent_response_path else None,
        "agent_response_validation": _artifact_rel(agent_response_validation_path) if agent_response_validation_path else None,
        "agent_generator": _artifact_rel(agent_generator_path) if agent_generator_path else None,
        "agent_repair_guidance": (agent_response_validation or {}).get("repair_guidance") or [],
        "context_health": context_health,
        "agent_next_action": agent_next_action,
        "agent_submission": agent_submission,
        "baseline": args.strategy,
        "symbol": args.symbol,
        "watchlist": watchlist,
        "watchlist_ranking": watchlist_ranking,
        "context": context,
        "candidates": write_results,
        "compare": compare_result,
        "ranking": (compare_result.get("data") or {}).get("ranking"),
        "winner": winner,
        "rejected_reasons": (compare_result.get("data") or {}).get("rejected_reasons"),
        "portfolio_risk_summary": (compare_result.get("data") or {}).get("portfolio_risk_summary"),
        "next_step": (
            f"Paper activated {winner}; monitor paper report."
            if args.mode == "paper" and promotion.get("activated")
            else (
                f"Review {winner}; dry_run did not activate current."
                if winner and args.mode == "dry_run"
                else "No candidate passed gates; keep baseline and generate another batch."
            )
        ),
        "promotion": promotion,
        "activation_result": activation_result,
        "paper_report": paper_report,
        "candidate_retention": cleanup_result,
        "current_before": current_before,
        "current_after": current_after,
        "current_changed": current_changed,
    }
    response["ok"] = bool(decision["ok"])
    if args.mode == "dry_run" and current_changed:
        response["ok"] = False
        response["error"] = _error_payload(
            "current_changed",
            "dry_run changed config/strategies/current; fail closed",
            {"current_before": current_before, "current_after": current_after},
        )
    elif paper_gate_failed:
        response["error"] = _error_payload(
            "promotion_gate_failed",
            "Paper mode did not activate because promotion gate failed",
            {"promotion": promotion, "activation_result": activation_result},
        )
    elif paper_activation_failed:
        response["error"] = _error_payload(
            "paper_activation_failed",
            "Paper mode promotion was eligible but activation failed",
            {"promotion": promotion, "activation_result": activation_result},
        )
    elif not compare_result.get("ok"):
        response["error"] = _error_payload("compare_failed", "Strategy comparison failed", compare_result.get("error"))

    json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
