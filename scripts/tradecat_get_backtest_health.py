#!/usr/bin/env python3
"""Backtest health - unified domain read model."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAME = "tradecat_get_backtest_health"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "backtest"


def _collect_runs(artifacts_dir: Path) -> list[dict]:
    runs: list[dict] = []
    if artifacts_dir.exists():
        for entry in sorted(artifacts_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            metrics = entry / "metrics.json"
            if metrics.exists():
                try:
                    with open(metrics) as f:
                        m = json.load(f)
                    runs.append(
                        {
                            "run_id": entry.name,
                            "status": "ok",
                            "net_pnl": m.get("net_pnl"),
                            "total_return_pct": m.get("total_return_pct"),
                            "max_drawdown_pct": m.get("max_drawdown_pct"),
                        }
                    )
                except Exception:
                    runs.append({"run_id": entry.name, "status": "parse_error"})
            else:
                runs.append({"run_id": entry.name, "status": "no_metrics"})
    return runs


def build_payload(artifacts_dir: Path = ARTIFACTS_DIR, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    runs = _collect_runs(artifacts_dir)
    warnings = []
    if not runs:
        warnings.append("no backtest runs found")
    return {
        "ok": True,
        "tool": TOOL_NAME,
        "ts": now.isoformat(),
        "source": "local",
        "request": {},
        "data": {
            "total_runs": len(runs),
            "latest_runs": runs[:5],
        },
        "error": None,
        "warnings": warnings,
        "schema_version": "1.0",
    }


def main():
    result = build_payload()
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
