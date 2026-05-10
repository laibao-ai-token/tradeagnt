"""tradecat analyze sub-command."""
from __future__ import annotations

import click


@click.command()
@click.option("--symbol", required=True, help="Symbol to analyze, e.g. BTCUSDT")
@click.option("--market", default="crypto", help="Market type (crypto, equity, fund)")
def analyze(symbol: str, market: str) -> None:
    """Analyze a single symbol."""
    click.echo(f"[analyze] symbol={symbol} market={market} — placeholder")
