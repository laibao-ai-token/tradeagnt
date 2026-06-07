"""Load and fingerprint agent trade thesis payloads."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

AGENT_TRADE_THESIS_SCHEMA = "tradecat_auto.agent_trade_thesis.v1"
SCHEMA_VERSION = "1.0.0"


def repo_root() -> Path:
    from tradecat.core.paper_trading.paths import find_tradeagnt_repo_root

    return find_tradeagnt_repo_root()


def schema_path() -> Path:
    return repo_root() / "contracts" / "agent_trade_thesis.schema.json"


def load_thesis_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("thesis must be a JSON object")
    return data


def load_thesis_path(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"missing_file: {p}")
    return load_thesis_text(p.read_text(encoding="utf-8"))


def load_thesis_stdin() -> dict[str, Any]:
    return load_thesis_text(sys.stdin.read())


def thesis_hash(thesis: dict[str, Any]) -> str:
    canonical = json.dumps(thesis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def thesis_id(thesis: dict[str, Any]) -> str:
    raw = str(thesis.get("thesis_id") or "").strip()
    if raw:
        return raw
    return thesis_hash(thesis)
