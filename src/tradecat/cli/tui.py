"""tradecat tui sub-command — launch TUI directly."""
from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command()
@click.option("--refresh", type=float, default=2.0, help="刷新间隔秒数")
@click.option("--limit", type=int, default=500, help="每次刷新最大行数")
@click.option("--no-quote", is_flag=True, help="禁用报价行")
def tui(refresh: float, limit: int, no_quote: bool) -> None:
    """Launch the TradeCat TUI signal dashboard."""
    from pathlib import Path
    from tradecat.tui.tui import run
    repo_root = Path(__file__).resolve().parents[2]
    db_path = str(repo_root / "libs" / "database" / "services" / "signal-service" / "signal_history.db")
    run(db_path, refresh_s=refresh, limit=limit)
