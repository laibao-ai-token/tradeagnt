#!/usr/bin/env python3
"""Context pack command - bundles all research data in one call."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_NAME = "tradecat_get_context_pack"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]

QUOTES_CMD = REPO_ROOT / "scripts" / "tradecat_get_quotes.py"
SIGNALS_CMD = REPO_ROOT / "scripts" / "tradecat_get_signals.py"
NEWS_CMD = REPO_ROOT / "scripts" / "tradecat_get_news.py"
BACKTEST_CMD = REPO_ROOT / "scripts" / "tradecat_get_backtest_health.py"

FRESHNESS_LIMITS = {
    "quotes": 300,  # 5 minutes
    "signals": 600,  # 10 minutes
    "news": 1800,  # 30 minutes
    "backtest": 86400,  # 1 day
}


def run_command(cmd: Path, args: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [sys.executable, str(cmd)] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            parsed = json.loads(result.stdout)
            if parsed.get("ok") is False:
                return {
                    "ok": False,
                    "error": parsed.get("error", "command failed"),
                    "data": parsed.get("data"),
                    "warnings": parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else [],
                }
            return parsed
        except json.JSONDecodeError:
            return {"ok": False, "error": result.stderr.strip() or "non-JSON output", "data": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None}


def _parse_ts(ts_value: Any):
    if not ts_value or not isinstance(ts_value, str):
        return None
    try:
        return datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
    except Exception:
        return None


def _freshness_block(payload: dict[str, Any] | None, limit_seconds: int, now: datetime):
    ts_value = (payload or {}).get("ts")
    parsed_ts = _parse_ts(ts_value)
    age = None
    if parsed_ts is not None:
        age = max(0, int((now - parsed_ts).total_seconds()))
    stale = age is None or age > limit_seconds
    return {"ts": ts_value, "age_seconds": age, "stale": stale, "limit_seconds": limit_seconds}


def _append_unique(target: list[str], message: str) -> None:
    text = str(message or "").strip()
    if text and text not in target:
        target.append(text)


def _quote_available(quote_data: Any) -> bool:
    if not quote_data:
        return False
    if isinstance(quote_data, list) and quote_data:
        first = quote_data[0]
        if isinstance(first, dict) and first.get("ok") is False:
            return False
    return True


def _block_available(name: str, payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if name == "quotes":
        return _quote_available(data)
    if name in {"signals", "news"}:
        return bool(data)
    return data is not None


def _payload_warnings(name: str, payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("warnings")
    if not isinstance(raw, list):
        return []
    items: list[str] = []
    for warning in raw:
        text = str(warning or "").strip()
        if text:
            items.append(f"{name}: {text}")
    return items


def build_payload(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
    news_limit: int = 5,
    signal_limit: int = 10,
    runner=run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    warnings: list[str] = []

    quotes = runner(QUOTES_CMD, [symbol])
    signals = runner(SIGNALS_CMD, ["--symbol", symbol, "--timeframe", timeframe, "--limit", str(signal_limit)])
    news = runner(NEWS_CMD, ["--symbol", symbol, "--limit", str(news_limit)])
    backtest = runner(BACKTEST_CMD, [])

    blocks = {
        "quotes": quotes,
        "signals": signals,
        "news": news,
        "backtest": backtest,
    }

    freshness = {}
    risk_summary: list[str] = []
    for name, payload in blocks.items():
        freshness_block = _freshness_block(payload if isinstance(payload, dict) else None, FRESHNESS_LIMITS[name], now)
        freshness[name] = freshness_block
        available = _block_available(name, payload if isinstance(payload, dict) else None)
        if not available:
            _append_unique(warnings, f"{name} unavailable")
            _append_unique(risk_summary, f"{name} missing")
        elif freshness_block["stale"]:
            _append_unique(warnings, f"{name} stale (age={freshness_block['age_seconds']})")
        for warning in _payload_warnings(name, payload if isinstance(payload, dict) else None):
            _append_unique(warnings, warning)
            _append_unique(risk_summary, warning)

    result = {
        "ok": True,
        "tool": TOOL_NAME,
        "ts": now.isoformat(),
        "source": "local",
        "request": {
            "symbol": symbol,
            "timeframe": timeframe,
            "news_limit": news_limit,
            "signal_limit": signal_limit,
        },
        "data": {
            "quotes": quotes.get("data"),
            "signals": signals.get("data"),
            "news": news.get("data"),
            "backtest_health": backtest.get("data"),
            "freshness": freshness,
            "risk_summary": risk_summary,
        },
        "error": None,
        "warnings": warnings,
        "schema_version": "1.1",
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Get context pack")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--news-limit", type=int, default=5)
    parser.add_argument("--signal-limit", type=int, default=10)
    args = parser.parse_args()

    result = build_payload(
        symbol=args.symbol,
        timeframe=args.timeframe,
        news_limit=args.news_limit,
        signal_limit=args.signal_limit,
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
