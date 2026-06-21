"""E4 feedback pack builder.

This is intentionally read-only. It gathers paper state, recent agent audit
rows, and recent signal history into one envelope so the next Agent step has
evidence for a human-reviewed follow-up.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from tradecat.agent.audit import tail_audit
from tradecat.agent.envelope import Envelope
from tradecat.agent.report import build_paper_report
from tradecat.core.signals.history_read import (
    fetch_recent_signals,
    probe_signal_history,
    resolve_history_db_path,
)


def _compact_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": row.get("ts"),
        "thesis_id": row.get("thesis_id"),
        "symbol": row.get("symbol"),
        "market": row.get("market"),
        "direction": row.get("direction"),
        "outcome": row.get("outcome"),
        "error_code": row.get("error_code"),
        "gates": row.get("gates"),
        "warnings": row.get("warnings") or [],
        "fill": row.get("fill"),
    }


def _audit_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = Counter(str(row.get("outcome") or "unknown") for row in rows)
    errors = Counter(str(row.get("error_code")) for row in rows if row.get("error_code"))
    warnings = Counter()
    for row in rows:
        for warning in row.get("warnings") or []:
            warnings[str(warning)] += 1
    return {
        "total": len(rows),
        "outcomes": dict(outcomes),
        "error_codes": dict(errors),
        "warnings": dict(warnings),
    }


def _compact_paper_data(paper_data: dict[str, Any]) -> dict[str, Any]:
    positions = [
        {
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "qty": p.get("qty"),
            "entry_price": p.get("entry_price"),
            "margin": p.get("margin"),
            "leverage": p.get("leverage"),
            "unrealized_pnl": p.get("unrealized_pnl"),
        }
        for p in paper_data.get("positions") or []
        if isinstance(p, dict)
    ]
    return {
        "account_id": paper_data.get("account_id"),
        "account_name": paper_data.get("account_name"),
        "nav": paper_data.get("nav"),
        "cash_available": paper_data.get("cash_available"),
        "pnl": paper_data.get("pnl"),
        "pnl_pct": paper_data.get("pnl_pct"),
        "positions": positions,
        "recent_rejects": paper_data.get("recent_rejects") or [],
    }


def _build_observations(
    *,
    audit_rows: list[dict[str, Any]],
    audit_summary: dict[str, Any],
    paper_data: dict[str, Any],
    signal_rows: list[dict[str, Any]],
    signal_available: bool,
) -> list[str]:
    observations: list[str] = []
    outcomes = audit_summary.get("outcomes") or {}
    errors = audit_summary.get("error_codes") or {}
    warnings = audit_summary.get("warnings") or {}

    if not audit_rows:
        observations.append("No recent agent paper decisions were found.")
    else:
        observations.append(
            f"Recent agent decisions: {outcomes.get('accept', 0)} accepted, "
            f"{outcomes.get('reject', 0)} rejected, {outcomes.get('watch_only', 0)} watch-only."
        )

    if errors:
        top_error, count = max(errors.items(), key=lambda item: item[1])
        observations.append(f"Most frequent reject reason is {top_error} ({count}x).")

    if warnings:
        top_warning, count = max(warnings.items(), key=lambda item: item[1])
        observations.append(f"Most frequent warning is {top_warning} ({count}x).")

    raw_positions = paper_data.get("positions") or []
    positions = [p for p in raw_positions if isinstance(p, dict)]
    open_positions = [p for p in positions if str(p.get("side", "")).upper() != "NEUTRAL"]
    if open_positions:
        observations.append(f"Paper account has {len(open_positions)} open position(s).")
    else:
        observations.append("Paper account has no open positions.")

    if signal_available:
        observations.append(f"Signal history contributed {len(signal_rows)} recent row(s).")
    else:
        observations.append("Signal history is unavailable; feedback is based on audit and paper state only.")

    return observations


def _build_recommendations(
    *,
    audit_summary: dict[str, Any],
    signal_available: bool,
) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    outcomes = audit_summary.get("outcomes") or {}
    errors = audit_summary.get("error_codes") or {}
    warnings = audit_summary.get("warnings") or {}

    if errors.get("agent_sizing_required") or errors.get("agent_thesis_schema_invalid"):
        recommendations.append(
            {
                "type": "thesis_contract",
                "action": "fix_required_fields",
                "reason": "Recent thesis submissions failed schema or sizing gates.",
            }
        )

    if errors.get("agent_data_stale") or warnings.get("freshness_warn"):
        recommendations.append(
            {
                "type": "data_freshness",
                "action": "refresh_context_before_submit",
                "reason": "Recent decisions had stale or freshness-warning market data.",
            }
        )

    if errors.get("agent_position_conflict") or warnings.get("position_conflict"):
        recommendations.append(
            {
                "type": "position_review",
                "action": "review_existing_position_before_new_thesis",
                "reason": "Recent decisions encountered open-position conflict.",
            }
        )

    if outcomes.get("reject", 0) > outcomes.get("accept", 0):
        recommendations.append(
            {
                "type": "gate_review",
                "action": "inspect_rejects_before_next_submit",
                "reason": "Rejects outnumber accepted paper decisions in the recent audit window.",
            }
        )

    if not signal_available:
        recommendations.append(
            {
                "type": "signal_context",
                "action": "run_or_import_signal_history",
                "reason": "No readable signal history was available for this feedback pack.",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "type": "human_review",
                "action": "review_feedback_before_strategy_changes",
                "reason": "No blocking issue was detected; keep the next step human-approved.",
            }
        )

    return recommendations


def build_feedback_pack(
    *,
    symbol: str | None = None,
    audit_limit: int = 20,
    signal_limit: int = 10,
) -> Envelope:
    audit_limit = max(1, min(int(audit_limit), 200))
    signal_limit = max(0, min(int(signal_limit), 100))
    symbol_filter = (symbol or "").strip() or None

    audit_rows = tail_audit(limit=audit_limit, symbol=symbol_filter)
    compact_audit = [_compact_audit_row(row) for row in audit_rows]
    summary = _audit_summary(audit_rows)

    paper_env = build_paper_report(symbol=symbol_filter, include_rejects=min(10, audit_limit))
    paper_data = _compact_paper_data(paper_env.data or {})

    db_path = resolve_history_db_path(None)
    signal_available, signal_message = probe_signal_history(db_path)
    signal_rows: list[dict[str, Any]] = []
    if signal_available and signal_limit > 0:
        signal_rows = [
            row.to_dict()
            for row in fetch_recent_signals(
                db_path=db_path,
                symbol=symbol_filter,
                timeframe=None,
                limit=signal_limit,
            )
        ]

    observations = _build_observations(
        audit_rows=audit_rows,
        audit_summary=summary,
        paper_data=paper_data,
        signal_rows=signal_rows,
        signal_available=signal_available,
    )
    recommendations = _build_recommendations(
        audit_summary=summary,
        signal_available=signal_available,
    )

    return Envelope(
        ok=True,
        data={
            "symbol": symbol_filter,
            "audit": {
                "summary": summary,
                "recent_decisions": compact_audit,
            },
            "paper": paper_data,
            "signals": {
                "source": {
                    "db_path": str(db_path),
                    "available": signal_available,
                    "message": signal_message,
                },
                "recent": signal_rows,
            },
            "observations": observations,
            "recommendations": recommendations,
            "next_step_policy": {
                "may_submit_paper": False,
                "may_write_strategy": False,
                "requires_human_review": True,
            },
        },
    )
