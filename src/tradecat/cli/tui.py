"""tradecat tui sub-command."""
from __future__ import annotations

import click


@click.command()
def tui() -> None:
    """Launch the TradeCat TUI."""
    click.echo("[tui] — placeholder")
