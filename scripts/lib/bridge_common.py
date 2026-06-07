"""Shared utilities for bridge scripts (tradecat_get_*.py, bridge_*.py)."""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """UTC ISO-8601 timestamp with Z suffix, microseconds stripped."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
