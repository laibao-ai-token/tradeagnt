#!/usr/bin/env python3
"""Bridge: dry-run thesis gates (no paper, no audit)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tradecat.agent.submit import validate_thesis_only  # noqa: E402

TOOL = "tradecat_agent_thesis_validate"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--stdin", action="store_true")
    args = parser.parse_args()
    env = validate_thesis_only(input_path=args.input, use_stdin=args.stdin)
    payload = {"tool": TOOL, **env.to_dict()}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
