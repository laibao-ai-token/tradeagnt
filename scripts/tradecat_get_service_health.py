#!/usr/bin/env python3
"""Service health check command for TradeCat."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAME = "tradecat_get_service_health"
SCRIPT_PATH = Path(__file__).resolve()


def check_service(name: str, port: int = None) -> str:
    """Check if a service process is running."""
    try:
        import psutil
        for proc in psutil.process_iter(['name', 'cmdline']):
            if proc.info['name'] and proc.info['cmdline']:
                cmdline = ' '.join(proc.info['cmdline'])
                if name in cmdline:
                    return "running"
    except ImportError:
        pass
    return "stopped"


def check_database(path: str) -> str:
    """Check if a database file exists and is accessible."""
    if not path:
        return "not_configured"
    db_path = Path(path)
    if db_path.exists():
        return "ok"
    return "not_found"


def _resolve_indicator_db(repo_root: Path, override: str | None = None) -> Path:
    if override:
        return Path(override)
    indicator_db = os.environ.get("INDICATOR_SQLITE_PATH", "")
    if indicator_db:
        return Path(indicator_db)
    return repo_root / "libs" / "database" / "services" / "telegram-service" / "market_data.db"


def build_payload(
    *,
    service_checker=check_service,
    database_checker=check_database,
    indicator_db_override: str | None = None,
    now=None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    repo_root = SCRIPT_PATH.parents[1]
    signal_db = repo_root / "libs" / "database" / "services" / "signal-service" / "signal_history.db"
    cooldown_db = repo_root / "libs" / "database" / "services" / "signal-service" / "cooldown.db"
    indicator_db = _resolve_indicator_db(repo_root, indicator_db_override)

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "ts": now.isoformat(),
        "source": "local",
        "request": {},
        "data": {
            "services": {
                "signal_service": service_checker("signal-service"),
                "trading_service": service_checker("trading-service"),
                "collector_service": service_checker("collector-service"),
            },
            "databases": {
                "signal_history": database_checker(str(signal_db)),
                "cooldown": database_checker(str(cooldown_db)),
                "indicator": database_checker(str(indicator_db)),
            },
            "timestamp": now.isoformat(),
        },
        "error": None,
        "warnings": [],
        "schema_version": "1.0",
    }


def main():
    result = build_payload()
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
