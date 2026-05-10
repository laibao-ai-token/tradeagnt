"""fetch sub-command: pull market data from a remote provider."""
from __future__ import annotations

import asyncio

import click

from tradecat.core.providers.registry import ProviderRegistry


@click.command()
@click.argument("symbol")
@click.option(
    "--provider",
    default="binance",
    help="数据源提供者标识 (binance|gate|rss_news)",
)
@click.option("--timeframe", default="1h", help="K线周期 (1m|5m|15m|1h|4h|1d)")
@click.option("--limit", default=10, help="返回条数")
def fetch(symbol: str, provider: str, timeframe: str, limit: int) -> None:
    """拉取市场 K 线数据并打印到终端."""
    registry = ProviderRegistry()
    registry.auto_register()

    async def _run() -> None:
        p = registry.resolve(symbol)
        df = await p.fetch_klines(symbol, timeframe, limit)
        click.echo(df.to_string(index=False))
        if hasattr(p, "close"):
            await p.close()

    asyncio.run(_run())
