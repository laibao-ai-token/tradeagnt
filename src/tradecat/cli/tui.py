"""tradecat tui sub-command — launch TUI directly."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click


def _ensure_services(repo_root: Path) -> None:
    """启动 collector-service 和 signal-service（幂等：已在运行则跳过）。"""
    # collector-service
    collector_pid = repo_root / "run" / "collector-service.pid"
    collector_running = collector_pid.exists() and subprocess.run(
        ["kill", "-0", collector_pid.read_text().strip()],
        check=False, capture_output=True,
    ).returncode == 0
    if not collector_running:
        start_sh = repo_root / "scripts" / "start.sh"
        if start_sh.exists():
            click.echo("[TUI] 正在启动 collector-service...")
            subprocess.run(
                ["/bin/bash", str(start_sh), "start-collector"],
                check=False,
            )

    # signal-service
    signal_dir = repo_root / "services" / "signal-service"
    signal_pid = signal_dir / "run" / "signal-service.pid"
    signal_running = signal_pid.exists() and subprocess.run(
        ["kill", "-0", signal_pid.read_text().strip()],
        check=False, capture_output=True,
    ).returncode == 0
    if not signal_running and signal_dir.exists():
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
    from pathlib import Path
    from tradecat.tui.tui import run
    repo_root = Path(__file__).resolve().parents[3]

    # 自动启动依赖服务
    _ensure_services(repo_root)

    db_path = str(repo_root / "libs" / "database" / "services" / "signal-service" / "signal_history.db")
    run(db_path, refresh_s=refresh, limit=limit)
