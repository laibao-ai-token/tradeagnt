"""tradecat tui sub-command — launch TUI directly."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click


def _truthy_env(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or default).strip().lower() in {"1", "true", "yes", "on"}


def _ensure_services(repo_root: Path) -> None:
    """Optional legacy service bootstrap (off by default in monolith)."""
    if not _truthy_env("TUI_AUTO_START_COLLECTOR", "0"):
        return

    collector_pid = repo_root / "run" / "collector-service.pid"
    collector_running = collector_pid.exists() and subprocess.run(
        ["kill", "-0", collector_pid.read_text().strip()],
        check=False,
        capture_output=True,
    ).returncode == 0
    if not collector_running:
        start_sh = repo_root / "scripts" / "start.sh"
        if start_sh.exists():
            click.echo("[TUI] 正在启动 collector（或 on-demand 剖面）...")
            subprocess.run(
                ["/bin/bash", str(start_sh), "start-collector"],
                check=False,
            )

    if not _truthy_env("TUI_AUTO_START_SIGNAL", "0"):
        return

    signal_dir = repo_root / "services" / "signal-service"
    if not signal_dir.exists():
        return

    signal_pid = signal_dir / "run" / "signal-service.pid"
    signal_running = signal_pid.exists() and subprocess.run(
        ["kill", "-0", signal_pid.read_text().strip()],
        check=False,
        capture_output=True,
    ).returncode == 0
    if not signal_running:
        click.echo("[TUI] 正在启动 signal-service...")
        subprocess.run(
            ["/bin/bash", str(signal_dir / "scripts" / "start.sh"), "start"],
            check=False,
        )


@click.command()
@click.option("--refresh", type=float, default=2.0, help="刷新间隔秒数")
@click.option("--limit", type=int, default=500, help="每次刷新最大行数")
@click.option("--no-quote", is_flag=True, help="禁用报价行")
def tui(refresh: float, limit: int, no_quote: bool) -> None:
    """Launch the TradeCat TUI signal dashboard."""
    from tradecat.core.pipeline.profile import bootstrap_pipeline_profile
    from tradecat.tui.tui import run

    repo_root = Path(__file__).resolve().parents[3]

    _ensure_services(repo_root)

    profile = bootstrap_pipeline_profile(repo_root=repo_root, only_if_unset=True)
    db_path = (
        profile.signal_db_path
        if profile and profile.signal_db_path
        else str(repo_root / "libs" / "database" / "services" / "signal-service" / "signal_history.db")
    )
    run(db_path, refresh_s=refresh, limit=limit)


if __name__ == "__main__":
    tui()
