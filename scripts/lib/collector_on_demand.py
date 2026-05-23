#!/usr/bin/env python3
"""Collector CLI stub when ``services/collector-service`` is absent (on-demand data mode)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable


COLLECTOR_KEYS = {
    "crypto_kline": "COLLECTOR_CRYPTO_KLINE_ENABLED",
    "crypto_metrics": "COLLECTOR_CRYPTO_METRICS_ENABLED",
    "orderbook": "COLLECTOR_CRYPTO_ORDERBOOK_ENABLED",
    "equity": "COLLECTOR_EQUITY_ENABLED",
    "fund_cn": "COLLECTOR_FUND_CN_ENABLED",
    "news": "COLLECTOR_NEWS_ENABLED",
}


def _env_enabled(name: str) -> bool:
    key = COLLECTOR_KEYS[name]
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return False
    return raw not in {"0", "false", "no", "off"}


def _enabled_from_env() -> list[str]:
    enabled = [name for name in COLLECTOR_KEYS if _env_enabled(name)]
    return sorted(enabled)


def _parse_only_exclude(argv: list[str]) -> tuple[list[str], list[str]]:
    only: list[str] = []
    exclude: list[str] = []
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token.startswith("--only="):
            only.extend(x.strip() for x in token.split("=", 1)[1].split(",") if x.strip())
        elif token == "--only" and idx + 1 < len(argv):
            idx += 1
            only.extend(x.strip() for x in argv[idx].split(",") if x.strip())
        elif token.startswith("--exclude="):
            exclude.extend(x.strip() for x in token.split("=", 1)[1].split(",") if x.strip())
        elif token == "--exclude" and idx + 1 < len(argv):
            idx += 1
            exclude.extend(x.strip() for x in argv[idx].split(",") if x.strip())
        idx += 1
    return only, exclude


def _apply_selectors(
    enabled: Iterable[str],
    *,
    only: list[str],
    exclude: list[str],
) -> list[str]:
    names = list(enabled)
    if only:
        allow = {x.strip() for x in only if x.strip()}
        names = [n for n in names if n in allow]
    if exclude:
        deny = {x.strip() for x in exclude if x.strip()}
        names = [n for n in names if n not in deny]
    return sorted(names)


def build_payload(argv: list[str] | None = None) -> dict[str, object]:
    args = list(argv or sys.argv[1:])
    only, exclude = _parse_only_exclude(args)
    run_mode = any(token in {"--run", "run"} for token in args)

    enabled = _enabled_from_env()
    if only:
        selected = sorted({x.strip() for x in only if x.strip()})
        if exclude:
            deny = {x.strip() for x in exclude if x.strip()}
            selected = [x for x in selected if x not in deny]
    else:
        selected = _apply_selectors(enabled, only=[], exclude=exclude)

    return {
        "data_mode": "on_demand",
        "collector_service": "absent",
        "mode": "run" if run_mode else "status",
        "enabled_collectors": selected,
        "runnable_collectors": selected,
        "collector_count": len(selected),
        "message": "collector-service not in repo; using on-demand providers (see docs/pipeline/DATA_COLLECTION.md)",
    }


def main(argv: list[str] | None = None) -> int:
    print(json.dumps(build_payload(argv), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
