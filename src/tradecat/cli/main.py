"""TradeCat CLI root command."""
from __future__ import annotations

import click

from tradecat import __version__
from tradecat.cli import analyze, backtest, connector, daemon, execute, fetch, indicator, migrate, signal, tui


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="tradecat")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """TradeCat — 通用金融分析引擎 CLI."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def main() -> None:
    cli.add_command(analyze.analyze)
    cli.add_command(backtest.backtest)
    cli.add_command(connector.connector_cmd)
    cli.add_command(daemon.daemon)
    cli.add_command(execute.execute_cmd)
    cli.add_command(fetch.fetch)
    cli.add_command(indicator.indicator_cmd)
    cli.add_command(migrate.migrate_cmd)
    cli.add_command(signal.signal_cmd)
    cli.add_command(tui.tui)
    cli()


if __name__ == "__main__":
    main()
