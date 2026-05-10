"""indicator sub-command: run a technical indicator on fetched market data."""
from __future__ import annotations

import asyncio

import click

from tradecat.core.indicators import auto_register
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.providers.registry import ProviderRegistry


@click.command(name="indicator")
@click.argument("indicator_name")
@click.argument("symbol")
@click.option("--provider", default="binance", help="数据源提供者标识")
@click.option("--timeframe", default="1h", help="K线周期 (1m|5m|15m|1h|4h|1d)")
@click.option("--limit", default=100, help="返回条数")
@click.option("--tail", default=10, help="打印最后 N 行")
def indicator_cmd(
    indicator_name: str,
    symbol: str,
    provider: str,
    timeframe: str,
    limit: int,
    tail: int,
) -> None:
    """对指定 symbol 运行技术指标并打印结果."""
    registry = ProviderRegistry()
    registry.auto_register()
    auto_register()  # register all indicators

    async def _run() -> None:
        try:
            p = registry.resolve_by_name(provider)
            df = await p.fetch_klines(symbol, timeframe, limit)

            ind_registry = IndicatorRegistry()
            meta = ind_registry.get(indicator_name)
            result = meta.func(df, **meta.params)
            click.echo(result.tail(tail).to_string(index=False))
        except ValueError as e:
            raise click.ClickException(str(e))
        except (ConnectionError, RuntimeError) as e:
            raise click.ClickException(str(e))
        finally:
            for prov in registry.list_providers():
                if hasattr(prov, "close"):
                    try:
                        await prov.close()
                    except Exception:
                        pass

    asyncio.run(_run())
