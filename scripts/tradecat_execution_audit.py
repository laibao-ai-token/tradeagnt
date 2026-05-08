#!/usr/bin/env python3
"""Execution audit CLI entry point."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
SERVICE_SRC = REPO_ROOT / "services" / "signal-service" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from execution_protocol.protocol import ExecutionProtocol
from execution_protocol.models import ExecutionPhase

TOOL_NAME = "tradecat_execution_audit"
DEFAULT_EXECUTION_AUDIT_DIR = REPO_ROOT / "artifacts" / "execution_audit"


def _parse_float_arg(value: object, name: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"invalid {name}: {value}") from exc


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "Usage: tradecat_execution_audit.py <command> [args]",
            "commands": ["start", "validate", "stage", "confirm", "execute", "sync", "fail", "replay", "list"]
        }, indent=2))
        return

    cmd = sys.argv[1]
    log_dir = Path(os.environ.get("TRADECAT_EXECUTION_AUDIT_DIR", str(DEFAULT_EXECUTION_AUDIT_DIR)))
    protocol = ExecutionProtocol(log_dir=str(log_dir))
    now = datetime.now(timezone.utc)
    request = {"command": cmd, "argv": sys.argv[2:]}

    if cmd == "start" and len(sys.argv) >= 6:
        try:
            size_pct = _parse_float_arg(sys.argv[6], "size_pct") if len(sys.argv) > 6 else 0.1
        except ValueError as exc:
            result = {"ok": False, "error_code": "invalid_argument", "error": str(exc)}
        else:
            request.update(
                {
                    "intent_id": sys.argv[2],
                    "order_id": sys.argv[3],
                    "symbol": sys.argv[4],
                    "side": sys.argv[5],
                    "size_pct": size_pct,
                }
            )
            state = protocol.start_execution(
                intent_id=sys.argv[2],
                order_id=sys.argv[3],
                symbol=sys.argv[4],
                side=sys.argv[5],
                size_pct=size_pct,
            )
            result = {"ok": True, "trace_id": state.trace_id}

    elif cmd == "validate" and len(sys.argv) >= 3:
        trace_id = sys.argv[2]
        passed = sys.argv[3].lower() == "true" if len(sys.argv) > 3 else True
        request.update({"trace_id": trace_id, "passed": passed})
        state = protocol.validate(trace_id, passed)
        result = {"ok": True, "status": state.status.value if state else "not_found"}

    elif cmd == "stage" and len(sys.argv) >= 3:
        request.update({"trace_id": sys.argv[2]})
        state = protocol.stage(sys.argv[2])
        result = {"ok": True, "status": state.status.value if state else "not_found"}

    elif cmd == "confirm" and len(sys.argv) >= 3:
        request.update({"trace_id": sys.argv[2]})
        state = protocol.confirm(sys.argv[2])
        result = {"ok": True, "status": state.status.value if state else "not_found"}

    elif cmd == "execute" and len(sys.argv) >= 4:
        try:
            fill_price = _parse_float_arg(sys.argv[3], "fill_price")
        except ValueError as exc:
            result = {"ok": False, "error_code": "invalid_argument", "error": str(exc)}
        else:
            request.update({"trace_id": sys.argv[2], "fill_price": fill_price})
            state = protocol.execute(sys.argv[2], fill_price)
            result = {"ok": True, "status": state.status.value if state else "not_found"}

    elif cmd == "sync" and len(sys.argv) >= 3:
        request.update({"trace_id": sys.argv[2]})
        state = protocol.sync(sys.argv[2])
        result = {"ok": True, "status": state.status.value if state else "not_found"}

    elif cmd == "fail" and len(sys.argv) >= 5:
        trace_id = sys.argv[2]
        phase_raw = sys.argv[3].strip().lower()
        reason = sys.argv[4]
        request.update({"trace_id": trace_id, "phase": phase_raw, "reason": reason})
        try:
            phase = ExecutionPhase(phase_raw)
        except ValueError:
            result = {"ok": False, "error_code": "invalid_argument", "error": f"Invalid phase: {phase_raw}"}
        else:
            state = protocol.fail(trace_id, phase, reason)
            result = {"ok": True, "status": state.status.value if state else "not_found"}

    elif cmd == "replay" and len(sys.argv) >= 3:
        request.update({"trace_id": sys.argv[2]})
        replay = protocol.replay(sys.argv[2])
        if replay is None:
            result = {"ok": False, "error_code": "trace_not_found", "error": f"trace not found: {sys.argv[2]}"}
        else:
            result = {"ok": True, "replay": replay}

    elif cmd == "list":
        traces = protocol.get_all_traces()
        result = {"ok": True, "traces": traces}

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
