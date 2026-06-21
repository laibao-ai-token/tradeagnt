#!/usr/bin/env python3
"""Bridge: Pi / harness -> read-only feedback pack envelope JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tradecat.agent.feedback import build_feedback_pack  # noqa: E402

TOOL = "tradecat_agent_feedback_pack"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="")
    parser.add_argument("--audit-limit", type=int, default=20)
    parser.add_argument("--signal-limit", type=int, default=10)
    args = parser.parse_args()

    env = build_feedback_pack(
        symbol=args.symbol or None,
        audit_limit=args.audit_limit,
        signal_limit=args.signal_limit,
    )
    payload = {"tool": TOOL, **env.to_dict()}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
