"""Read-only access to ``signal_history.db`` for CLI bridges and agents."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from tradecat.core.paper_trading.paths import default_signal_db_path, find_tradeagnt_repo_root


@dataclass(frozen=True)
class SignalHistoryRow:
    id: int
    timestamp: str
    symbol: str
    signal_type: str
    direction: str
    strength: int
    message: str | None
    timeframe: str | None
    price: float | None
    source: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def resolve_history_db_path(override: str | None = None) -> Path:
    """Resolve ``signal_history.db`` from override, env, or repo default."""
    raw = (override or os.getenv("SIGNAL_HISTORY_DB", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return default_signal_db_path(find_tradeagnt_repo_root())


def probe_signal_history(db_path: Path | str) -> tuple[bool, str]:
    """Return whether the DB file exists and ``signal_history`` is readable."""
    path = Path(db_path)
    if not path.is_file():
        return False, f"database file not found: {path}"
    try:
        with sqlite3.connect(str(path), timeout=2) as conn:
            conn.execute("SELECT 1 FROM signal_history LIMIT 1").fetchone()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _symbol_filter_values(symbol: str) -> list[str]:
    text = symbol.strip()
    if not text:
        return []
    values = {text, text.upper(), text.replace("_", ""), text.replace("-", "")}
    try:
        from tradecat.core.symbols import (
            crypto_pair_to_compact,
            infer_market_from_symbol,
            normalize_symbol,
            normalize_symbols_for_strategy,
        )

        market = infer_market_from_symbol(text)
        for item in normalize_symbols_for_strategy([text], market):
            values.add(str(item))
        norm = normalize_symbol(text, market)
        if norm:
            values.add(norm)
            compact = crypto_pair_to_compact(norm)
            if compact:
                values.add(compact)
    except Exception:
        pass
    return sorted(values)


def _has_extra_column(conn: sqlite3.Connection) -> bool:
    try:
        rows = conn.execute("PRAGMA table_info(signal_history)").fetchall()
    except Exception:
        return False
    for row in rows:
        name = str(row[1])
        if name == "extra":
            return True
    return False


def fetch_recent_signals(
    *,
    db_path: Path | str,
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = 20,
) -> list[SignalHistoryRow]:
    """Fetch recent rows newest-first, with optional symbol/timeframe filters."""
    path = Path(db_path)
    where = ["1=1"]
    params: list[object] = []

    if symbol and symbol.strip():
        candidates = _symbol_filter_values(symbol)
        if candidates:
            placeholders = ",".join("?" * len(candidates))
            where.append(f"symbol IN ({placeholders})")
            params.extend(candidates)

    if timeframe and timeframe.strip():
        where.append("timeframe = ?")
        params.append(timeframe.strip())

    params.append(max(1, min(int(limit), 500)))

    with sqlite3.connect(str(path), timeout=2) as conn:
        conn.row_factory = sqlite3.Row
        extra_expr = "extra" if _has_extra_column(conn) else "NULL AS extra"
        sql = f"""
            SELECT id, timestamp, symbol, signal_type, direction, strength,
                   message, timeframe, price, source, {extra_expr}
            FROM signal_history
            WHERE {' AND '.join(where)}
            ORDER BY id DESC
            LIMIT ?
        """
        rows = conn.execute(sql, params).fetchall()

    out: list[SignalHistoryRow] = []
    for row in rows:
        signal_type = str(row["signal_type"])
        extra_raw = row["extra"]
        if isinstance(extra_raw, str) and extra_raw.strip():
            try:
                payload = json.loads(extra_raw)
                if isinstance(payload, dict):
                    signal_type = str(payload.get("rule_name") or signal_type)
            except Exception:
                pass
        out.append(
            SignalHistoryRow(
                id=int(row["id"]),
                timestamp=str(row["timestamp"]),
                symbol=str(row["symbol"]),
                signal_type=signal_type,
                direction=str(row["direction"]),
                strength=int(row["strength"] or 0),
                message=row["message"],
                timeframe=row["timeframe"],
                price=float(row["price"]) if row["price"] is not None else None,
                source=row["source"],
            )
        )
    return out
