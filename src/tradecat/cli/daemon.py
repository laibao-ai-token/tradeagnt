"""tradecat daemon sub-command."""
from __future__ import annotations

import click


@click.command()
def daemon() -> None:
    """Run the TradeCat daemon."""
    click.echo("[daemon] — placeholder")
