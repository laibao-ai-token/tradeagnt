#!/usr/bin/env python3
"""Bridge: Pi / harness → submit_thesis envelope JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tradecat.agent.submit import submit_thesis  # noqa: E402

TOOL = "tradecat_agent_submit_thesis"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--stdin", action="store_true")
    args = parser.parse_args()
    env = submit_thesis(input_path=args.input, use_stdin=args.stdin, dry_run=False)
    payload = {"tool": TOOL, **env.to_dict()}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
