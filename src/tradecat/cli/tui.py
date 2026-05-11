"""tradecat tui sub-command — bridge to legacy TUI service."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click


@click.command()
@click.option("--refresh", type=float, default=2.0, help="刷新间隔秒数")
@click.option("--limit", type=int, default=500, help="每次刷新最大行数")
@click.option("--no-quote", is_flag=True, help="禁用报价行")
def tui(refresh: float, limit: int, no_quote: bool) -> None:
    """Launch the TradeCat TUI signal dashboard."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    tui_dir = repo_root / "services-preview" / "tui-service"

    if not tui_dir.exists():
        raise click.ClickException(
            f"Legacy TUI not found at {tui_dir}. "
            "Run 'tradecat tui' from repo root with services-preview/ intact."
        )

    # Compose PYTHONPATH so legacy imports resolve
    env = os.environ.copy()
    py_paths = [
        str(tui_dir / "src"),
        str(repo_root / "libs"),
    ]
    if env.get("PYTHONPATH"):
        py_paths.insert(0, env["PYTHONPATH"])
    env["PYTHONPATH"] = ":".join(py_paths)

    # Build argv forwarded to legacy TUI
    args = [sys.executable, "-m", "src"]
    args.extend(["--refresh", str(refresh)])
    args.extend(["--limit", str(limit)])
    if no_quote:
        args.append("--no-quote")

    result = subprocess.run(args, cwd=str(tui_dir), env=env)
    sys.exit(result.returncode)
