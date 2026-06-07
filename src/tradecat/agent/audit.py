"""Append-only agent audit journal (JSONL)."""
from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_SCHEMA = "tradeagnt.agent_audit.v1"

_cached_audit_path: Path | None = None


def audit_path() -> Path:
    global _cached_audit_path
    if _cached_audit_path is not None:
        return _cached_audit_path
    from tradecat.core.paper_trading.paths import default_data_dir, find_tradeagnt_repo_root

    root = find_tradeagnt_repo_root()
    env = os.getenv("TRADEAGNT_AUDIT_PATH", "").strip()
    if env:
        _cached_audit_path = Path(env).expanduser().resolve()
    else:
        _cached_audit_path = default_data_dir(root) / "agent_audit.jsonl"
    return _cached_audit_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_audit(record: dict[str, Any]) -> Path:
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _utc_now(), "schema": AUDIT_SCHEMA, **record}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def tail_audit(*, limit: int = 50, symbol: str | None = None) -> list[dict[str, Any]]:
    path = audit_path()
    if not path.is_file():
        return []
    # 用 deque 只保留最后 limit 行，避免全文件读入内存
    with path.open("r", encoding="utf-8") as fh:
        recent_lines: deque[str] = deque(fh, maxlen=limit * 2 if symbol else limit)
    rows: list[dict[str, Any]] = []
    for line in reversed(recent_lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if symbol and str(row.get("symbol", "")).upper() != symbol.upper():
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def find_accepted(thesis_id: str) -> dict[str, Any] | None:
    for row in tail_audit(limit=500):
        if row.get("thesis_id") == thesis_id and row.get("outcome") == "accept":
            return row
    return None
