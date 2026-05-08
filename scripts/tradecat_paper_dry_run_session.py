#!/usr/bin/env python3
"""Run a fixed-duration paper trading dry-run session without mutating portfolio state."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
SERVICE_ROOT = REPO_ROOT / "services" / "signal-service"
SERVICE_SRC = SERVICE_ROOT / "src"
sys.path.insert(0, str(REPO_ROOT / "libs"))
sys.path.insert(0, str(SERVICE_ROOT))
sys.path.insert(0, str(SERVICE_SRC))

from paper_trading import PaperTradingOrchestrator

TOOL_NAME = "tradecat_paper_dry_run_session"
DEFAULT_PAPER_ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "paper_trading"
DEFAULT_EXECUTION_AUDIT_DIR = REPO_ROOT / "artifacts" / "execution_audit"


def _parse_positive_float(value: object, name: str) -> float:
    try:
        parsed = float(value)
    except Exception as exc:
        raise ValueError(f"invalid {name}: {value}") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be > 0")
    return parsed


def _parse_positive_int(value: object, name: str) -> int:
    try:
        parsed = int(value)
    except Exception as exc:
        raise ValueError(f"invalid {name}: {value}") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be > 0")
    return parsed


def _parse_signal_ts(value: str | None, fallback: datetime) -> datetime:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError(f"invalid signal_ts: {value}") from exc


def _build_orchestrator(*, artifacts_dir: str | Path | None, execution_audit_dir: str | Path | None) -> PaperTradingOrchestrator:
    return PaperTradingOrchestrator(
        artifacts_dir=Path(artifacts_dir or os.environ.get("TRADECAT_PAPER_ARTIFACTS_DIR", str(DEFAULT_PAPER_ARTIFACTS_DIR))),
        execution_log_dir=Path(execution_audit_dir or os.environ.get("TRADECAT_EXECUTION_AUDIT_DIR", str(DEFAULT_EXECUTION_AUDIT_DIR))),
    )


def build_payload(
    *,
    symbol: str,
    side: str,
    size_pct: float,
    price: float,
    duration_seconds: int = 3600,
    interval_seconds: int = 60,
    max_ticks: int | None = None,
    signal_ts: str | None = None,
    score: int = 80,
    reason: str = "dry_run_session",
    now: datetime | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    artifacts_dir: str | Path | None = None,
    execution_audit_dir: str | Path | None = None,
) -> dict[str, Any]:
    symbol = str(symbol).strip().upper()
    side = str(side).strip().upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"invalid side: {side}")

    size_pct = _parse_positive_float(size_pct, "size_pct")
    price = _parse_positive_float(price, "price")
    duration_seconds = _parse_positive_int(duration_seconds, "duration_seconds")
    interval_seconds = _parse_positive_int(interval_seconds, "interval_seconds")
    if max_ticks is not None:
        max_ticks = _parse_positive_int(max_ticks, "max_ticks")

    session_now = now or datetime.now(timezone.utc)
    session_end = session_now + timedelta(seconds=duration_seconds)
    last_signal_ts = _parse_signal_ts(signal_ts, session_now)
    sleep_fn = sleep_fn or time.sleep

    orchestrator = _build_orchestrator(artifacts_dir=artifacts_dir, execution_audit_dir=execution_audit_dir)
    stats_before = orchestrator.get_stats()
    report_before = orchestrator.get_execution_report_summary(limit=200)

    target_ticks = max(1, duration_seconds // interval_seconds)
    if duration_seconds % interval_seconds != 0:
        target_ticks += 1
    if max_ticks is not None:
        target_ticks = min(target_ticks, max_ticks)

    results: list[dict[str, Any]] = []
    guard_passed_ticks = 0
    guard_failed_ticks = 0
    estimated_fee_total = 0.0
    estimated_slippage_total = 0.0

    for idx in range(target_ticks):
        tick_time = session_now + timedelta(seconds=idx * interval_seconds)
        tick_signal_ts = last_signal_ts + timedelta(seconds=idx * interval_seconds)
        dry_run_result = orchestrator.dry_run(
            symbol=symbol,
            side=side,
            size_pct=size_pct,
            execution_price=price,
            score=score,
            reason=reason,
            last_signal_ts=tick_signal_ts,
        )
        guard = dry_run_result.get("guard", {})
        passed = bool(guard.get("passed", False))
        if passed:
            guard_passed_ticks += 1
        else:
            guard_failed_ticks += 1
        estimated_fee_total += float(dry_run_result.get("estimated_fee", 0.0) or 0.0)
        estimated_slippage_total += float(dry_run_result.get("estimated_slippage", 0.0) or 0.0)
        results.append(
            {
                "tick": idx + 1,
                "tick_ts": tick_time.isoformat(),
                "signal_ts": tick_signal_ts.isoformat(),
                "guard_passed": passed,
                "risk_level": guard.get("risk_level"),
                "failed_rules": guard.get("failed_rules", []),
                "estimated_fee": dry_run_result.get("estimated_fee"),
                "estimated_slippage": dry_run_result.get("estimated_slippage"),
                "result": dry_run_result,
            }
        )
        if idx < target_ticks - 1:
            sleep_fn(float(interval_seconds))

    stats_after = orchestrator.get_stats()
    report_after = orchestrator.get_execution_report_summary(limit=200)

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "ts": session_now.isoformat(),
        "source": "local",
        "request": {
            "symbol": symbol,
            "side": side,
            "size_pct": size_pct,
            "price": price,
            "duration_seconds": duration_seconds,
            "interval_seconds": interval_seconds,
            "max_ticks": max_ticks,
            "signal_ts": last_signal_ts.isoformat(),
            "score": score,
            "reason": reason,
        },
        "data": {
            "mode": "dry_run_session",
            "session": {
                "start_ts": session_now.isoformat(),
                "end_ts": session_end.isoformat(),
                "target_ticks": target_ticks,
            },
            "summary": {
                "ticks_completed": len(results),
                "guard_passed_ticks": guard_passed_ticks,
                "guard_failed_ticks": guard_failed_ticks,
                "estimated_fee_total": estimated_fee_total,
                "estimated_slippage_total": estimated_slippage_total,
            },
            "results": results,
            "stats_before": stats_before,
            "stats_after": stats_after,
            "report_before": report_before,
            "report_after": report_after,
        },
        "error": None,
    }


def _build_error_payload(message: str, *, request: dict[str, Any] | None = None, code: str = "invalid_argument") -> dict[str, Any]:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "local",
        "request": request or {},
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fixed-duration paper trading dry-run session")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", required=True)
    parser.add_argument("--size-pct", required=True)
    parser.add_argument("--price", required=True)
    parser.add_argument("--duration-seconds", default="3600")
    parser.add_argument("--interval-seconds", default="60")
    parser.add_argument("--max-ticks")
    parser.add_argument("--signal-ts")
    parser.add_argument("--score", default="80")
    parser.add_argument("--reason", default="dry_run_session")
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--execution-audit-dir")
    args = parser.parse_args()

    request = vars(args).copy()
    try:
        payload = build_payload(
            symbol=args.symbol,
            side=args.side,
            size_pct=args.size_pct,
            price=args.price,
            duration_seconds=args.duration_seconds,
            interval_seconds=args.interval_seconds,
            max_ticks=args.max_ticks,
            signal_ts=args.signal_ts,
            score=int(args.score),
            reason=args.reason,
            artifacts_dir=args.artifacts_dir,
            execution_audit_dir=args.execution_audit_dir,
        )
    except ValueError as exc:
        payload = _build_error_payload(str(exc), request=request)
    except Exception as exc:  # pragma: no cover
        payload = _build_error_payload(str(exc), request=request, code="runtime_error")
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
