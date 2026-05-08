#!/usr/bin/env python3
"""Symbol snapshot command - unified domain read model."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_NAME = "tradecat_get_symbol_snapshot"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
QUOTES_CMD = REPO_ROOT / "scripts" / "tradecat_get_quotes.py"
SIGNALS_CMD = REPO_ROOT / "scripts" / "tradecat_get_signals.py"


def run_cmd(cmd: Path, args: list[str]) -> dict[str, Any]:
    try:
        r = subprocess.run([sys.executable, str(cmd)] + args, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "data": None,
            "error": {
                "code": "command_timeout",
                "message": f"command timed out: {cmd.name}",
                "details": {"command": str(cmd), "timeout_seconds": 15},
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "data": None,
            "error": {
                "code": "command_execution_failed",
                "message": str(exc),
                "details": {"command": str(cmd)},
            },
        }
    stdout = (r.stdout or "").strip()
    if not stdout:
        return {
            "ok": False,
            "data": None,
            "error": {
                "code": "empty_output",
                "message": f"command returned empty output: {cmd.name}",
                "details": {"command": str(cmd), "returncode": r.returncode},
            },
        }
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "data": None,
            "error": {
                "code": "invalid_json_output",
                "message": f"command output is not valid json: {cmd.name}",
                "details": {"command": str(cmd), "returncode": r.returncode},
            },
        }
    if not isinstance(parsed, dict):
        return {
            "ok": False,
            "data": None,
            "error": {
                "code": "invalid_payload",
                "message": f"command output is not an object: {cmd.name}",
                "details": {"command": str(cmd), "type": type(parsed).__name__},
            },
        }
    return parsed


def _normalize_error(error: object, *, code: str, message: str) -> dict[str, Any]:
    if isinstance(error, dict):
        return {
            "code": str(error.get("code") or code),
            "message": str(error.get("message") or message),
            "details": error.get("details") if isinstance(error.get("details"), dict) else {},
        }
    if error:
        return {"code": code, "message": str(error), "details": {}}
    return {"code": code, "message": message, "details": {}}


def _normalize_source_result(raw: object, *, source: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "ok": False,
            "data": None,
            "error": {
                "code": "invalid_source_payload",
                "message": f"{source} returned non-object payload",
                "details": {"type": type(raw).__name__},
            },
        }

    data = raw.get("data")
    ok = raw.get("ok")
    error = raw.get("error")
    if ok is False:
        return {
            "ok": False,
            "data": data,
            "error": _normalize_error(
                error,
                code="source_failed",
                message=f"{source} returned ok=false",
            ),
        }
    if data is None and error:
        return {
            "ok": False,
            "data": None,
            "error": _normalize_error(
                error,
                code="source_data_missing",
                message=f"{source} returned no data",
            ),
        }
    return {"ok": True, "data": data, "error": None}


def _quote_available(quote_data: Any) -> bool:
    if not quote_data:
        return False
    if isinstance(quote_data, list) and quote_data:
        first = quote_data[0]
        if isinstance(first, dict) and first.get("ok") is False:
            return False
    return True


def build_payload(symbol: str, timeframe: str, *, runner=run_cmd, now=None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    warnings: list[str] = []

    quotes_source = _normalize_source_result(runner(QUOTES_CMD, [symbol]), source="quotes")
    quotes_data = quotes_source.get("data")
    if not _quote_available(quotes_data):
        warnings.append("quotes unavailable")

    signals_source = _normalize_source_result(
        runner(SIGNALS_CMD, ["--symbol", symbol, "--timeframe", timeframe, "--limit", "5"]),
        source="signals",
    )
    signals_data = signals_source.get("data")
    if not signals_data:
        warnings.append("signals unavailable")

    result = {
        "ok": True,
        "tool": TOOL_NAME,
        "ts": now.isoformat(),
        "source": "local",
        "request": {"symbol": symbol, "timeframe": timeframe},
        "data": {
            "symbol": symbol,
            "quote": quotes_data,
            "latest_signals": signals_data,
            "source_status": {
                "quotes": {"ok": quotes_source["ok"], "error": quotes_source["error"]},
                "signals": {"ok": signals_source["ok"], "error": signals_source["error"]},
            },
        },
        "error": None,
        "warnings": warnings,
        "schema_version": "1.1",
    }
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--timeframe", default="1h")
    args = p.parse_args()

    result = build_payload(args.symbol, args.timeframe)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
