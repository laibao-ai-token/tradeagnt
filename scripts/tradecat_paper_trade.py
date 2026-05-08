#!/usr/bin/env python3
"""Paper Trading CLI entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
SERVICE_ROOT = REPO_ROOT / "services" / "signal-service"
SERVICE_SRC = REPO_ROOT / "services" / "signal-service" / "src"
sys.path.insert(0, str(REPO_ROOT / "libs"))
sys.path.insert(0, str(SERVICE_ROOT))
sys.path.insert(0, str(SERVICE_SRC))

from paper_trading import PaperTradingOrchestrator

TOOL_NAME = "tradecat_paper_trade"
DEFAULT_PAPER_ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "paper_trading"
DEFAULT_EXECUTION_AUDIT_DIR = REPO_ROOT / "artifacts" / "execution_audit"
BACKTEST_SUMMARY_SCRIPT = REPO_ROOT / "scripts" / "tradecat_get_backtest_summary.py"


def _parse_float_arg(value: object, name: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"invalid {name}: {value}") from exc


def _parse_int_arg(value: object, name: str) -> int:
    try:
        return int(value)
    except Exception as exc:
        raise ValueError(f"invalid {name}: {value}") from exc


def _parse_signal_ts_value(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("signal timestamp cannot be empty")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError(f"invalid signal_ts: {value}") from exc


def _extract_signal_ts_arg(args: list[str]) -> tuple[list[str], datetime | None]:
    tokens = list(args)
    parsed: datetime | None = None
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token not in {"--signal-ts", "--signal_ts"}:
            idx += 1
            continue
        if idx + 1 >= len(tokens):
            raise ValueError(f"missing value for {token}")
        if parsed is not None:
            raise ValueError("signal_ts provided multiple times")
        parsed = _parse_signal_ts_value(tokens[idx + 1])
        del tokens[idx : idx + 2]
    return tokens, parsed


def _run_backtest_summary(*, run_id: str, artifacts_root: str | None = None) -> dict[str, Any]:
    cmd = [sys.executable, str(BACKTEST_SUMMARY_SCRIPT), "--run-id", run_id]
    if artifacts_root:
        cmd.extend(["--artifacts-root", artifacts_root])
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return {
            "ok": False,
            "error_code": "backtest_summary_empty_output",
            "error": completed.stderr.strip() or "backtest summary returned empty output",
        }
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error_code": "backtest_summary_invalid_json",
            "error": "backtest summary output is not valid json",
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "error_code": "backtest_summary_invalid_payload",
            "error": "backtest summary output is not an object",
        }
    return payload


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _build_compare_payload(*, paper_stats: dict[str, Any], backtest_payload: dict[str, Any]) -> dict[str, Any]:
    backtest_data = backtest_payload.get("data") if isinstance(backtest_payload, dict) else {}
    backtest_metrics = (backtest_data or {}).get("metrics") if isinstance(backtest_data, dict) else {}
    paper_attr = paper_stats.get("attribution") if isinstance(paper_stats, dict) else {}

    paper_return_pct = _safe_float(paper_stats.get("return_pct"))
    paper_trade_count = _safe_int(paper_stats.get("total_trades"))
    backtest_return_pct = _safe_float(backtest_metrics.get("total_return_pct"))
    backtest_trade_count = _safe_int(backtest_metrics.get("trade_count"))

    return {
        "paper": {
            "initial_equity": _safe_float(paper_stats.get("initial_equity")),
            "current_equity": _safe_float(paper_stats.get("current_equity")),
            "peak_equity": _safe_float(paper_stats.get("peak_equity")),
            "return_pct": paper_return_pct,
            "trade_count": paper_trade_count,
            "open_positions": _safe_int(paper_stats.get("open_positions")),
            "filled": _safe_int((paper_attr or {}).get("filled")),
            "rejected": _safe_int((paper_attr or {}).get("rejected")),
            "failed": _safe_int((paper_attr or {}).get("failed")),
            "total_fee": _safe_float((paper_attr or {}).get("total_fee")),
            "total_slippage_cost": _safe_float((paper_attr or {}).get("total_slippage_cost")),
            "net_cash_impact": _safe_float((paper_attr or {}).get("net_cash_impact")),
            "report_file": (paper_attr or {}).get("report_file"),
        },
        "backtest": {
            "run_id": (backtest_data or {}).get("run_id"),
            "mode": (backtest_metrics or {}).get("mode"),
            "total_return_pct": backtest_return_pct,
            "max_drawdown_pct": _safe_float((backtest_metrics or {}).get("max_drawdown_pct")),
            "trade_count": backtest_trade_count,
            "win_rate_pct": _safe_float((backtest_metrics or {}).get("win_rate_pct")),
            "profit_factor": _safe_float((backtest_metrics or {}).get("profit_factor")),
            "sharpe": _safe_float((backtest_metrics or {}).get("sharpe")),
            "summary_file": ((backtest_data or {}).get("artifacts") or {}).get("summary", {}).get("path"),
        },
        "delta": {
            "return_pct": paper_return_pct - backtest_return_pct,
            "trade_count": paper_trade_count - backtest_trade_count,
        },
        "notes": [
            "paper trading uses simplified execution and equity accounting",
            "backtest uses historical replay metrics and may diverge on timing, slippage, and fees",
            "treat this compare output as alignment screening rather than production-grade pnl parity",
        ],
    }


def _parse_candidate_option_args(args: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "score": 80,
        "reason": "test",
        "idempotency_key": None,
        "reuse_finalized": False,
    }
    value_flags = {
        "--symbol": "symbol",
        "--side": "side",
        "--size-pct": "size_pct",
        "--size_pct": "size_pct",
        "--score": "score",
        "--reason": "reason",
        "--idempotency-key": "idempotency_key",
        "--idempotency_key": "idempotency_key",
    }
    bool_flags = {"--reuse-finalized", "--reuse_finalized"}

    i = 0
    while i < len(args):
        token = args[i]
        if token in bool_flags:
            parsed["reuse_finalized"] = True
            i += 1
            continue
        key = value_flags.get(token)
        if key is None:
            raise ValueError(f"unexpected candidate argument: {token}")
        if i + 1 >= len(args):
            raise ValueError(f"missing value for {token}")
        parsed[key] = args[i + 1]
        i += 2

    required = ["symbol", "side", "size_pct"]
    missing = [name for name in required if not parsed.get(name)]
    if missing:
        raise ValueError(
            "candidate requires symbol/side/size_pct; use positional "
            "`candidate BTCUSDT LONG 0.10` or flags `--symbol --side --size-pct`"
        )

    try:
        parsed["size_pct"] = float(parsed["size_pct"])
    except Exception as exc:
        raise ValueError(f"invalid size_pct: {parsed.get('size_pct')}") from exc
    try:
        parsed["score"] = int(parsed["score"])
    except Exception as exc:
        raise ValueError(f"invalid score: {parsed.get('score')}") from exc
    parsed["symbol"] = str(parsed["symbol"])
    parsed["side"] = str(parsed["side"])
    parsed["reason"] = str(parsed["reason"])
    if parsed.get("idempotency_key") is not None:
        parsed["idempotency_key"] = str(parsed["idempotency_key"])
    return parsed


def _parse_candidate_args(args: list[str]) -> dict[str, Any]:
    if len(args) >= 3 and not args[0].startswith("--") and not args[1].startswith("--") and not args[2].startswith("--"):
        positional = {
            "symbol": args[0],
            "side": args[1],
            "size_pct": args[2],
            "score": 80,
            "reason": "test",
            "idempotency_key": None,
            "reuse_finalized": False,
        }
        trailing = args[3:]
        if trailing:
            option_flags = {
                "--score": "score",
                "--reason": "reason",
                "--idempotency-key": "idempotency_key",
                "--idempotency_key": "idempotency_key",
            }
            bool_flags = {"--reuse-finalized", "--reuse_finalized"}
            i = 0
            while i < len(trailing):
                token = trailing[i]
                if token in bool_flags:
                    positional["reuse_finalized"] = True
                    i += 1
                    continue
                key = option_flags.get(token)
                if key is None:
                    raise ValueError(f"unexpected candidate argument: {token}")
                if i + 1 >= len(trailing):
                    raise ValueError(f"missing value for {token}")
                positional[key] = trailing[i + 1]
                i += 2
        return _parse_candidate_option_args(
            [
                "--symbol",
                str(positional["symbol"]),
                "--side",
                str(positional["side"]),
                "--size-pct",
                str(positional["size_pct"]),
                "--score",
                str(positional["score"]),
                "--reason",
                str(positional["reason"]),
                *(
                    ["--idempotency-key", str(positional["idempotency_key"])]
                    if positional.get("idempotency_key") is not None
                    else []
                ),
                *(["--reuse-finalized"] if positional.get("reuse_finalized") else []),
            ]
        )
    return _parse_candidate_option_args(args)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "Usage: tradecat_paper_trade.py <command> [args]",
            "commands": [
                "init",
                "candidate",
                "candidate --symbol <symbol> --side <LONG|SHORT> --size-pct <pct> [--score 80] [--reason text] [--idempotency-key key] [--reuse-finalized]",
                "from-signal",
                "validate",
                "dry-run",
                "dry_run",
                "execute",
                "positions",
                "portfolio",
                "stats",
                "report",
                "compare",
            ],
        }, indent=2))
        return

    cmd = sys.argv[1]
    artifacts_dir = Path(os.environ.get("TRADECAT_PAPER_ARTIFACTS_DIR", str(DEFAULT_PAPER_ARTIFACTS_DIR)))
    execution_log_dir = Path(os.environ.get("TRADECAT_EXECUTION_AUDIT_DIR", str(DEFAULT_EXECUTION_AUDIT_DIR)))
    orchestrator = PaperTradingOrchestrator(
        artifacts_dir=artifacts_dir,
        execution_log_dir=execution_log_dir,
    )

    now = datetime.now(timezone.utc)
    request: dict[str, Any] = {"command": cmd, "argv": sys.argv[2:]}

    if cmd == "init":
        result = {"ok": True, "initialized": True}
    
    elif cmd == "positions":
        result = {"ok": True, "positions": orchestrator.get_positions()}
    
    elif cmd == "stats":
        result = {"ok": True, "stats": orchestrator.get_stats()}

    elif cmd == "portfolio":
        result = {"ok": True, "portfolio": orchestrator.get_portfolio_state()}

    elif cmd == "report":
        try:
            limit = _parse_int_arg(sys.argv[2], "limit") if len(sys.argv) >= 3 else 20
        except ValueError as exc:
            result = {"ok": False, "error_code": "invalid_argument", "error": str(exc)}
        else:
            request["limit"] = limit
            result = {"ok": True, "report": orchestrator.get_execution_report_summary(limit=limit)}

    elif cmd == "compare":
        try:
            args = list(sys.argv[2:])
            if not args:
                raise ValueError("compare requires --backtest-run-id <run_id>")
            run_id = ""
            artifacts_root: str | None = None
            idx = 0
            while idx < len(args):
                token = args[idx]
                if token == "--backtest-run-id":
                    if idx + 1 >= len(args):
                        raise ValueError("missing value for --backtest-run-id")
                    run_id = str(args[idx + 1]).strip()
                    idx += 2
                    continue
                if token == "--artifacts-root":
                    if idx + 1 >= len(args):
                        raise ValueError("missing value for --artifacts-root")
                    artifacts_root = str(args[idx + 1]).strip()
                    idx += 2
                    continue
                raise ValueError(f"unexpected compare argument: {token}")
            if not run_id:
                raise ValueError("compare requires --backtest-run-id <run_id>")
        except ValueError as exc:
            result = {"ok": False, "error_code": "invalid_argument", "error": str(exc)}
        else:
            request.update({"backtest_run_id": run_id, "artifacts_root": artifacts_root})
            backtest_payload = _run_backtest_summary(run_id=run_id, artifacts_root=artifacts_root)
            if not backtest_payload.get("ok"):
                result = {
                    "ok": False,
                    "error_code": backtest_payload.get("error_code", "backtest_summary_failed"),
                    "error": backtest_payload.get("error", "failed to load backtest summary"),
                    "backtest": backtest_payload,
                }
            else:
                result = {
                    "ok": True,
                    "compare": _build_compare_payload(
                        paper_stats=orchestrator.get_stats(),
                        backtest_payload=backtest_payload,
                    ),
                }
    
    elif cmd == "candidate":
        try:
            params = _parse_candidate_args(sys.argv[2:])
        except ValueError as exc:
            result = {
                "ok": False,
                "error_code": "invalid_candidate_args",
                "error": str(exc),
            }
        else:
            request.update(params)
            order = orchestrator.generate_candidate(
                symbol=params["symbol"],
                side=params["side"],
                size_pct=params["size_pct"],
                score=params["score"],
                reason=params["reason"],
                idempotency_key=params["idempotency_key"],
                reuse_finalized=bool(params.get("reuse_finalized")),
            )
            result = {"ok": True, "order": {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": order.qty,
                "score": order.entry_score,
                "reason": order.entry_reason,
                "idempotency_key": order.idempotency_key,
            }}

    elif cmd == "from-signal" and len(sys.argv) >= 3:
        try:
            symbol = sys.argv[2]
            timeframe = sys.argv[3] if len(sys.argv) >= 4 else None
            size_pct = _parse_float_arg(sys.argv[4], "size_pct") if len(sys.argv) >= 5 else 0.1
            min_strength = _parse_int_arg(sys.argv[5], "min_strength") if len(sys.argv) >= 6 else 50
            execution_price = _parse_float_arg(sys.argv[6], "execution_price") if len(sys.argv) >= 7 else None
            max_retries = _parse_int_arg(sys.argv[7], "max_retries") if len(sys.argv) >= 8 else 2
        except ValueError as exc:
            result = {"ok": False, "error_code": "invalid_argument", "error": str(exc)}
        else:
            generated = orchestrator.generate_candidate_from_latest_signal(
                symbol=symbol,
                timeframe=timeframe,
                size_pct=size_pct,
                min_strength=min_strength,
            )
            if not generated.get("ok"):
                result = {
                    "ok": False,
                    "error": generated.get("error"),
                    "error_code": generated.get("error_code"),
                    "signal": generated.get("signal"),
                }
            else:
                order = generated["order"]
                signal_data = generated["signal"]
                request.update(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "size_pct": size_pct,
                        "min_strength": min_strength,
                        "execution_price": execution_price,
                        "max_retries": max_retries,
                    }
                )
                result = {
                    "ok": True,
                    "order": {
                        "order_id": order.order_id,
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "qty": order.qty,
                        "score": order.entry_score,
                        "reason": order.entry_reason,
                    },
                    "signal": signal_data,
                }
                if execution_price is not None:
                    signal_ts = signal_data.get("signal_ts")
                    try:
                        parsed_signal_ts = (
                            datetime.fromisoformat(str(signal_ts).replace("Z", "+00:00")) if signal_ts else None
                        )
                    except Exception:
                        parsed_signal_ts = None
                    result["execution"] = orchestrator.confirm_and_execute_with_retry(
                        order.order_id,
                        execution_price=execution_price,
                        max_retries=max_retries,
                        last_signal_ts=parsed_signal_ts,
                    )
    
    elif cmd == "validate":
        try:
            tokens, signal_ts = _extract_signal_ts_arg(sys.argv[2:])
            if len(tokens) < 3:
                raise ValueError("validate requires <symbol> <side> <size_pct>")
            symbol = tokens[0]
            side = tokens[1]
            size_pct = _parse_float_arg(tokens[2], "size_pct")
        except ValueError as exc:
            result = {"ok": False, "error_code": "invalid_argument", "error": str(exc)}
        else:
            request.update(
                {
                    "symbol": symbol,
                    "side": side,
                    "size_pct": size_pct,
                    "signal_ts": signal_ts.isoformat() if signal_ts else None,
                }
            )
            result = orchestrator.validate(symbol, side, size_pct, last_signal_ts=signal_ts)
            result["ok"] = True
    
    elif cmd == "execute":
        try:
            tokens, signal_ts = _extract_signal_ts_arg(sys.argv[2:])
            if len(tokens) < 2:
                raise ValueError("execute requires <order_id> <price> [max_retries]")
            order_id = tokens[0]
            price = _parse_float_arg(tokens[1], "price")
            max_retries = _parse_int_arg(tokens[2], "max_retries") if len(tokens) >= 3 else 2
        except ValueError as exc:
            result = {"ok": False, "error_code": "invalid_argument", "error": str(exc)}
        else:
            request.update(
                {
                    "order_id": order_id,
                    "price": price,
                    "max_retries": max_retries,
                    "signal_ts": signal_ts.isoformat() if signal_ts else None,
                }
            )
            result = orchestrator.confirm_and_execute_with_retry(
                order_id,
                price,
                max_retries=max_retries,
                last_signal_ts=signal_ts,
            )
            result["ok"] = result.get("success", False)

    elif cmd in {"dry-run", "dry_run"}:
        try:
            tokens, signal_ts = _extract_signal_ts_arg(sys.argv[2:])
            if len(tokens) < 4:
                raise ValueError("dry-run requires <symbol> <side> <size_pct> <price>")
            symbol = tokens[0]
            side = tokens[1]
            size_pct = _parse_float_arg(tokens[2], "size_pct")
            price = _parse_float_arg(tokens[3], "price")
        except ValueError as exc:
            result = {"ok": False, "error_code": "invalid_argument", "error": str(exc)}
        else:
            request.update(
                {
                    "symbol": symbol,
                    "side": side,
                    "size_pct": size_pct,
                    "price": price,
                    "signal_ts": signal_ts.isoformat() if signal_ts else None,
                }
            )
            result = orchestrator.dry_run(
                symbol=symbol,
                side=side,
                size_pct=size_pct,
                execution_price=price,
                last_signal_ts=signal_ts,
            )
            result["ok"] = True

    else:
        result = {"ok": False, "error": f"Unknown command: {cmd}"}

    output = {
        "ok": result.get("ok", False),
        "tool": TOOL_NAME,
        "ts": now.isoformat(),
        "source": "local",
        "request": request,
        "data": result,
        "error": result.get("error"),
    }
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
