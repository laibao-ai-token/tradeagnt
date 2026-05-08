#!/usr/bin/env python3
"""Market state - unified domain read model."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAME = "tradecat_get_market_state"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
SERVICE_HEALTH_CMD = REPO_ROOT / "scripts" / "tradecat_get_service_health.py"


def _load_service_health():
    if not SERVICE_HEALTH_CMD.exists():
        return (
            None,
            {
                "ok": False,
                "error": {
                    "code": "service_health_script_missing",
                    "message": "service health script not found",
                    "details": {"command": str(SERVICE_HEALTH_CMD)},
                },
            },
            ["service health script not found"],
        )
    import subprocess
    try:
        r = subprocess.run([sys.executable, str(SERVICE_HEALTH_CMD)], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return json.loads(r.stdout), {"ok": True, "error": None}, []
        return (
            None,
            {
                "ok": False,
                "error": {
                    "code": "service_health_unavailable",
                    "message": "service health unavailable",
                    "details": {"returncode": r.returncode},
                },
            },
            ["service health unavailable"],
        )
    except Exception as exc:
        return (
            None,
            {
                "ok": False,
                "error": {
                    "code": "service_health_check_failed",
                    "message": str(exc),
                    "details": {"command": str(SERVICE_HEALTH_CMD)},
                },
            },
            [f"service health check failed: {exc}"],
        )


def build_payload(health_payload=None, *, now=None, warnings=None):
    now = now or datetime.now(timezone.utc)
    warnings_list = list(warnings or [])
    health_data = health_payload
    source_status = {"ok": True, "error": None}
    if health_data is None:
        health_data, source_status, generated_warnings = _load_service_health()
        warnings_list.extend(generated_warnings)
    elif isinstance(health_payload, dict) and health_payload.get("ok") is False:
        source_status = {
            "ok": False,
            "error": health_payload.get("error"),
        }

    result = {
        "ok": True,
        "tool": TOOL_NAME,
        "ts": now.isoformat(),
        "source": "local",
        "request": {},
        "data": {
            "services": health_data.get("data", {}).get("services", {}) if health_data else {},
            "databases": health_data.get("data", {}).get("databases", {}) if health_data else {},
            "source_status": {
                "service_health": source_status,
            },
        },
        "error": None,
        "warnings": warnings_list,
        "schema_version": "1.1",
    }
    return result


def main():
    result = build_payload()
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
