"""tradecat backtest sub-command."""
from __future__ import annotations

import click


@click.command()
@click.option(
    "--mode",
    type=click.Choice(["runner", "walkforward", "offline", "rule", "compare"]),
    required=True,
    help="Backtest mode",
)
@click.option("--config", type=click.Path(exists=True), help="Path to strategy config YAML")
def backtest(mode: str, config: str | None) -> None:
    """Run backtests."""
    click.echo(f"[backtest] mode={mode} config={config} — placeholder")
