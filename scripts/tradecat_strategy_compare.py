#!/usr/bin/env python3
"""Bridge: compare strategies with structured backtest output.

Runs scripts/bridge_backtest.py for a baseline and 1-4 candidate strategies,
then ranks successful strategies by conservative, explainable metrics.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
TOOL_NAME = "tradecat_strategy_compare"
BRIDGE_BACKTEST = REPO_ROOT / "scripts" / "bridge_backtest.py"


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _strategy_list(raw: str) -> list[str]:
    seen: set[str] = set()
    strategies: list[str] = []
    for item in (raw or "").split(","):
        strategy = item.strip()
        if strategy and strategy not in seen:
            seen.add(strategy)
            strategies.append(strategy)
    return strategies


def _run_backtest(
    *,
    strategy: str,
    symbol: str,
    market: str,
    days: int,
    timeframe: str,
    provider: str,
    min_strength: int,
    initial_equity: float | None,
    notional: float | None,
    timeout: float,
    paper: bool,
) -> dict[str, Any]:
    failure_context = {
        "strategy": strategy,
        "symbol": symbol,
        "market": market or None,
        "days": days,
        "timeframe": timeframe or None,
        "provider": provider or None,
        "min_strength": min_strength,
        "paper": paper,
    }
    if not BRIDGE_BACKTEST.is_file():
        return {
            **failure_context,
            "ok": False,
            "error": "bridge_backtest.py not found",
            "failure_context": failure_context,
        }

    cmd = [
        sys.executable,
        str(BRIDGE_BACKTEST),
        "--strategy",
        strategy,
        "--symbol",
        symbol,
        "--days",
        str(days),
        "--min-strength",
        str(min_strength),
        "--mode",
        "scan",
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
    if not paper:
        cmd += ["--no-paper"]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )
    except subprocess.TimeoutExpired:
        return {
            **failure_context,
            "ok": False,
            "error": "timeout",
            "score": None,
            "failure_context": {**failure_context, "timeout_s": timeout + 10},
        }
    except Exception as e:  # noqa: BLE001
        return {
            **failure_context,
            "ok": False,
            "error": str(e),
            "score": None,
            "failure_context": {**failure_context, "exception_type": e.__class__.__name__},
        }

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            **failure_context,
            "ok": False,
            "error": "invalid_backtest_json",
            "exit_code": result.returncode,
            "stderr_tail": result.stderr.splitlines()[-10:],
            "stdout_tail": result.stdout.splitlines()[-10:],
            "failure_context": {**failure_context, "exit_code": result.returncode},
        }

    data = payload.get("data") or {}
    signals = data.get("signals") or {}
    paper_data = data.get("paper") or {}
    summary = {
        "strategy": strategy,
        "ok": bool(payload.get("ok")),
        "exit_code": data.get("exit_code", result.returncode),
        "header": data.get("header"),
        "signals_total": signals.get("total"),
        "signals_buy": signals.get("buy"),
        "signals_sell": signals.get("sell"),
        "signals_strong": signals.get("strong"),
        "trades": paper_data.get("trades"),
        "closed_trades": paper_data.get("closed_trades"),
        "win_rate_pct": paper_data.get("win_rate_pct"),
        "max_drawdown_pct": paper_data.get("max_drawdown_pct"),
        "avg_hold_minutes": paper_data.get("avg_hold_minutes"),
        "exposure_pct": paper_data.get("exposure_pct"),
        "return_pct": paper_data.get("return_pct"),
        "realized_pnl": paper_data.get("realized_pnl"),
        "nav": paper_data.get("nav"),
        "error": payload.get("error"),
    }
    return summary


def _metric_number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _metric_optional(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _return_drawdown_ratio(return_pct: float | None, drawdown_pct: float | None) -> float | None:
    if return_pct is None or drawdown_pct is None:
        return None
    denominator = max(abs(float(drawdown_pct)), 0.01)
    return float(return_pct) / denominator


def _tail_text(value: Any) -> str:
    if value is None:
        return ""
    ignored = {"backtest error:", "error:"}
    if isinstance(value, list):
        lines = [str(item).strip() for item in value if str(item).strip() and str(item).strip().lower() not in ignored]
    else:
        lines = [line.strip() for line in str(value).splitlines() if line.strip() and line.strip().lower() not in ignored]
    return " | ".join(lines[-3:])


def _context_text(details: dict[str, Any], result: dict[str, Any]) -> str:
    source = details or result.get("failure_context") or result
    fields = {
        "strategy": source.get("strategy") or result.get("strategy"),
        "symbol": source.get("symbol") or result.get("symbol"),
        "market": source.get("market") or result.get("market"),
        "timeframe": source.get("timeframe") or result.get("timeframe"),
        "provider": source.get("provider") or result.get("provider"),
        "days": source.get("days") or result.get("days"),
        "exit_code": source.get("exit_code") or result.get("exit_code"),
    }
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "")]
    return ", ".join(parts)


def _failure_reason(result: dict[str, Any]) -> str | None:
    if result.get("ok"):
        return None

    error = result.get("error")
    parts: list[str] = []
    details: dict[str, Any] = {}
    if isinstance(error, dict):
        code = str(error.get("code") or "").strip()
        message = str(error.get("message") or "").strip()
        if code and message:
            parts.append(f"{code}: {message}")
        elif message:
            parts.append(message)
        elif code:
            parts.append(code)
        if isinstance(error.get("details"), dict):
            details = error["details"]
    elif error:
        parts.append(str(error).strip())

    diagnostic = str(details.get("diagnostic_summary") or "").strip()
    if diagnostic:
        parts.append(diagnostic)

    tail = _tail_text(details.get("stderr_tail")) or _tail_text(details.get("stdout_tail"))
    if not tail:
        tail = _tail_text(result.get("stderr_tail")) or _tail_text(result.get("stdout_tail"))
    if tail:
        parts.append(tail)

    context = _context_text(details, result)
    if context:
        parts.append(f"context: {context}")

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            deduped.append(part)
    return " | ".join(deduped)[:1000] or "backtest failed"


def _score_details(result: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    reasons: list[str] = []
    baseline_ok = bool((baseline or {}).get("ok"))
    baseline_return = _metric_optional((baseline or {}).get("return_pct")) if baseline_ok else None
    baseline_drawdown = _metric_optional((baseline or {}).get("max_drawdown_pct")) if baseline_ok else None
    baseline_win_rate = _metric_optional((baseline or {}).get("win_rate_pct")) if baseline_ok else None
    baseline_return_drawdown_ratio = _return_drawdown_ratio(baseline_return, baseline_drawdown) if baseline_ok else None
    return_value = _metric_optional(result.get("return_pct"))
    drawdown_value = _metric_optional(result.get("max_drawdown_pct"))
    win_rate_value = _metric_optional(result.get("win_rate_pct"))
    avg_hold_value = _metric_optional(result.get("avg_hold_minutes"))
    exposure_value = _metric_optional(result.get("exposure_pct"))
    trades = int(_metric_number(result.get("trades"), 0))
    signals_total = int(_metric_number(result.get("signals_total"), 0))
    return_pct = return_value if return_value is not None else 0.0
    drawdown_pct = drawdown_value if drawdown_value is not None else 0.0
    baseline_delta = (
        round(return_pct - baseline_return, 6)
        if result.get("ok") and baseline_return is not None and return_value is not None
        else None
    )
    drawdown_delta = (
        round(drawdown_pct - baseline_drawdown, 6)
        if result.get("ok") and baseline_drawdown is not None and drawdown_value is not None
        else None
    )
    return_drawdown_ratio = _return_drawdown_ratio(return_value, drawdown_value)
    return_drawdown_ratio_delta = (
        round(return_drawdown_ratio - baseline_return_drawdown_ratio, 6)
        if (
            result.get("ok")
            and return_drawdown_ratio is not None
            and baseline_return_drawdown_ratio is not None
        )
        else None
    )
    win_rate_delta = (
        round(win_rate_value - baseline_win_rate, 6)
        if result.get("ok") and baseline_win_rate is not None and win_rate_value is not None
        else None
    )

    if not result.get("ok"):
        reasons.append("backtest failed")
        return {
            "score": None,
            "score_parts": {
                "return_pct": return_value,
                "baseline_return_pct": baseline_return,
                "baseline_delta": baseline_delta,
                "max_drawdown_pct": drawdown_value,
                "baseline_max_drawdown_pct": baseline_drawdown,
                "drawdown_delta": drawdown_delta,
                "return_drawdown_ratio": return_drawdown_ratio,
                "baseline_return_drawdown_ratio": baseline_return_drawdown_ratio,
                "return_drawdown_ratio_delta": return_drawdown_ratio_delta,
                "win_rate_pct": win_rate_value,
                "baseline_win_rate_pct": baseline_win_rate,
                "win_rate_delta": win_rate_delta,
                "avg_hold_minutes": avg_hold_value,
                "exposure_pct": exposure_value,
                "trade_count": trades,
                "signals_total": signals_total,
                "drawdown_penalty": 0.0,
                "exposure_penalty": 0.0,
                "hold_penalty": 0.0,
                "win_rate_bonus": 0.0,
                "overtrade_penalty": 0.0,
                "low_trade_penalty": 0.0,
                "low_signal_penalty": 0.0,
                "failure_penalty": 1.0,
                "improvement_bonus": 0.0,
            },
            "gate": {"passed": False, "reasons": reasons},
            "failure_reason": _failure_reason(result),
        }

    if trades <= 0:
        reasons.append("no paper trades")
    if signals_total <= 0:
        reasons.append("no signals")
    if signals_total > 80:
        reasons.append("too many signals")

    if baseline_return is not None and return_pct < baseline_return:
        reasons.append("underperformed baseline return")
    if baseline_drawdown is not None and drawdown_value is not None and drawdown_delta is not None and drawdown_delta > 5.0:
        reasons.append("max drawdown worse than baseline")
    if exposure_value is not None and exposure_value > 80.0:
        reasons.append("paper exposure too high")

    drawdown_penalty = max(0.0, drawdown_pct) * 0.02
    exposure_penalty = max(0.0, (exposure_value or 0.0) - 50.0) * 0.002
    hold_penalty = max(0.0, (avg_hold_value or 0.0) - 240.0) * 0.0005
    overtrade_penalty = max(0.0, float(signals_total - 25)) * 0.01
    low_trade_penalty = 0.25 if trades <= 0 else 0.0
    low_signal_penalty = 0.1 if signals_total <= 0 else 0.0
    improvement_bonus = max(0.0, return_pct - (baseline_return or 0.0)) * 0.25 if baseline_return is not None else 0.0
    win_rate_bonus = (max(0.0, win_rate_value) / 100.0 * 0.05) if win_rate_value is not None else 0.0
    return_drawdown_bonus = (
        max(0.0, return_drawdown_ratio_delta) * 0.02
        if return_drawdown_ratio_delta is not None
        else 0.0
    )
    score = (
        return_pct
        - drawdown_penalty
        - exposure_penalty
        - hold_penalty
        - overtrade_penalty
        - low_trade_penalty
        - low_signal_penalty
        + improvement_bonus
        + win_rate_bonus
        + return_drawdown_bonus
    )
    return {
        "score": round(score, 6),
        "score_parts": {
            "return_pct": round(return_pct, 6),
            "baseline_return_pct": round(baseline_return, 6) if baseline_return is not None else None,
            "baseline_delta": baseline_delta,
            "max_drawdown_pct": round(drawdown_pct, 6) if drawdown_value is not None else None,
            "baseline_max_drawdown_pct": round(baseline_drawdown, 6) if baseline_drawdown is not None else None,
            "drawdown_delta": drawdown_delta,
            "return_drawdown_ratio": round(return_drawdown_ratio, 6) if return_drawdown_ratio is not None else None,
            "baseline_return_drawdown_ratio": round(baseline_return_drawdown_ratio, 6)
            if baseline_return_drawdown_ratio is not None
            else None,
            "return_drawdown_ratio_delta": return_drawdown_ratio_delta,
            "win_rate_pct": round(win_rate_value, 6) if win_rate_value is not None else None,
            "baseline_win_rate_pct": round(baseline_win_rate, 6) if baseline_win_rate is not None else None,
            "win_rate_delta": win_rate_delta,
            "avg_hold_minutes": round(avg_hold_value, 6) if avg_hold_value is not None else None,
            "exposure_pct": round(exposure_value, 6) if exposure_value is not None else None,
            "trade_count": trades,
            "signals_total": signals_total,
            "drawdown_penalty": round(drawdown_penalty, 6),
            "exposure_penalty": round(exposure_penalty, 6),
            "hold_penalty": round(hold_penalty, 6),
            "win_rate_bonus": round(win_rate_bonus, 6),
            "return_drawdown_bonus": round(return_drawdown_bonus, 6),
            "overtrade_penalty": round(overtrade_penalty, 6),
            "low_trade_penalty": round(low_trade_penalty, 6),
            "low_signal_penalty": round(low_signal_penalty, 6),
            "failure_penalty": 0.0,
            "improvement_bonus": round(improvement_bonus, 6),
        },
        "gate": {"passed": not reasons, "reasons": reasons},
        "failure_reason": None,
    }


def _rank_results(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    baseline = results[0] if results else None
    ranked: list[dict[str, Any]] = []
    for index, result in enumerate(results):
        score_details = _score_details(result, baseline)
        score = score_details["score"]
        gate = score_details["gate"]
        reasons = gate["reasons"]
        decision = "baseline" if index == 0 else "candidate"
        if index == 0:
            gate = {"passed": True, "reasons": []}
            reasons = []
        else:
            decision = "rejected" if not gate["passed"] or score is None else "eligible"
        item = {
            **result,
            "role": "baseline" if index == 0 else "candidate",
            "score": score,
            "score_parts": score_details["score_parts"],
            "baseline_delta": score_details["score_parts"].get("baseline_delta"),
            "gate": gate,
            "failure_reason": score_details["failure_reason"],
            "decision": decision,
            "rejected_reasons": reasons,
        }
        ranked.append(item)

    eligible = [r for r in ranked[1:] if r.get("decision") == "eligible" and r.get("score") is not None]
    eligible.sort(key=lambda r: (r.get("score") or -999999, _metric_number(r.get("return_pct"))), reverse=True)
    winner = eligible[0]["strategy"] if eligible else None
    for item in ranked:
        if item["strategy"] == winner:
            item["decision"] = "winner"
    return ranked, winner


def _portfolio_risk_summary(ranking: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [item for item in ranking if item.get("role") == "candidate"]
    exposures = [_metric_optional(item.get("exposure_pct")) for item in candidates]
    drawdowns = [_metric_optional(item.get("max_drawdown_pct")) for item in candidates]
    returns = [_metric_optional(item.get("return_pct")) for item in candidates]
    signals = [_metric_optional(item.get("signals_total")) for item in candidates]
    exposures = [value for value in exposures if value is not None]
    drawdowns = [value for value in drawdowns if value is not None]
    returns = [value for value in returns if value is not None]
    signals = [value for value in signals if value is not None]

    risk_flags: list[str] = []
    max_exposure = max(exposures) if exposures else None
    max_drawdown = max(drawdowns) if drawdowns else None
    min_return = min(returns) if returns else None
    max_signals = max(signals) if signals else None
    rejected_count = sum(1 for item in candidates if item.get("decision") == "rejected")
    failed_count = sum(1 for item in candidates if not item.get("ok"))

    if max_exposure is not None and max_exposure > 80.0:
        risk_flags.append("candidate exposure above 80%")
    if max_drawdown is not None and max_drawdown > 10.0:
        risk_flags.append("candidate max drawdown above 10%")
    if min_return is not None and min_return < 0:
        risk_flags.append("candidate negative return")
    if max_signals is not None and max_signals > 80:
        risk_flags.append("candidate signal count above gate")
    if failed_count:
        risk_flags.append("one or more candidate backtests failed")
    if candidates and rejected_count == len(candidates):
        risk_flags.append("all candidates rejected")

    if not candidates:
        risk_level = "unknown"
    elif failed_count or (max_exposure is not None and max_exposure > 80.0) or (max_drawdown is not None and max_drawdown > 10.0):
        risk_level = "high"
    elif risk_flags:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "scope": "candidate_set_single_symbol",
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "candidate_count": len(candidates),
        "eligible_count": sum(1 for item in candidates if item.get("decision") in {"eligible", "winner"}),
        "rejected_count": rejected_count,
        "failed_count": failed_count,
        "max_exposure_pct": round(max_exposure, 6) if max_exposure is not None else None,
        "max_drawdown_pct": round(max_drawdown, 6) if max_drawdown is not None else None,
        "min_return_pct": round(min_return, 6) if min_return is not None else None,
        "max_signals_total": int(max_signals) if max_signals is not None else None,
        "note": "Single-symbol candidate-set summary; not a cross-symbol correlation model.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare strategies with structured backtests.")
    parser.add_argument("--strategies", required=True, help="Comma-separated strategies; first one is baseline")
    parser.add_argument("--symbol", required=True, help="Symbol, e.g. BTC_USDT")
    parser.add_argument("--days", type=int, default=7, help="Lookback days")
    parser.add_argument("--market", default="", help="Market hint, e.g. crypto or us_stock")
    parser.add_argument("--timeframe", default="", help="Optional timeframe override")
    parser.add_argument("--provider", default="", help="Optional provider override")
    parser.add_argument("--min-strength", type=int, default=50, help="Min signal strength")
    parser.add_argument("--initial-equity", type=float, default=None, help="Optional paper initial equity")
    parser.add_argument("--notional", type=float, default=None, help="Optional paper notional")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-backtest timeout seconds")
    parser.add_argument("--no-paper", action="store_true", help="Disable paper simulation metrics")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    response = _base_response()
    strategies = _strategy_list(args.strategies)
    response["request"] = {
        "strategies": strategies,
        "symbol": args.symbol,
        "market": args.market or None,
        "days": args.days,
        "timeframe": args.timeframe or None,
        "provider": args.provider or None,
        "min_strength": args.min_strength,
        "paper": not args.no_paper,
    }

    if args.days <= 0:
        response["error"] = _error_payload("invalid_arguments", "--days must be > 0")
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if len(strategies) < 2:
        response["error"] = _error_payload("invalid_arguments", "Need baseline plus at least 1 candidate")
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    if len(strategies) > 6:
        response["error"] = _error_payload("invalid_arguments", "Max 6 strategies including baseline")
        json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1

    results = [
        _run_backtest(
            strategy=strategy,
            symbol=args.symbol,
            market=args.market,
            days=args.days,
            timeframe=args.timeframe,
            provider=args.provider,
            min_strength=args.min_strength,
            initial_equity=args.initial_equity,
            notional=args.notional,
            timeout=args.timeout,
            paper=not args.no_paper,
        )
        for strategy in strategies
    ]
    ranking, winner = _rank_results(results)
    portfolio_risk = _portfolio_risk_summary(ranking)
    response["ok"] = any(r.get("ok") for r in ranking)
    response["data"] = {
        "baseline": strategies[0],
        "candidates": strategies[1:],
        "ranking": ranking,
        "winner": winner,
        "portfolio_risk_summary": portfolio_risk,
        "rejected_reasons": {
            r["strategy"]: r.get("rejected_reasons") or []
            for r in ranking
            if r.get("role") == "candidate" and r.get("decision") == "rejected"
        },
        "next_step": (
            f"Review winner {winner}; keep dry_run unless explicitly promoting to paper."
            if winner
            else "No candidate beat the baseline gates; keep baseline and generate new candidates."
        ),
    }
    if not response["ok"]:
        response["error"] = _error_payload("all_backtests_failed", "No strategy produced a valid backtest")

    json.dump(response, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
