#!/usr/bin/env python3
"""Bridge: paper-report JSON for Pi."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tradecat.agent.report import build_paper_report  # noqa: E402

TOOL = "tradecat_agent_paper_report"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="")
    parser.add_argument("--include-rejects", type=int, default=5)
    args = parser.parse_args()
    env = build_paper_report(symbol=args.symbol or None, include_rejects=args.include_rejects)
    payload = {"tool": TOOL, **env.to_dict()}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
