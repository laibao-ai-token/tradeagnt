"""signal sub-command: run a strategy and output signals."""
from __future__ import annotations

import asyncio
import json

import click

from tradecat.core.indicators import auto_register as auto_register_indicators
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals import CooldownManager, SignalEngine, StrategyLoader


@click.command(name="signal")
@click.option("--config", required=True, help="策略YAML文件路径")
@click.option("--symbol", required=True, help="交易对")
@click.option("--provider", default="binance", help="数据源提供者")
@click.option("--data", help="本地 CSV 文件路径（离线模式）")
@click.option("--timeframe", default="1h", help="K线周期")
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["json", "table"]),
    default="table",
    help="输出格式",
)
def signal_cmd(
    config: str,
    symbol: str,
    provider: str,
    data: str | None,
    timeframe: str,
    output_format: str,
) -> None:
    """对指定 symbol 运行策略并输出信号."""
    strategy = StrategyLoader.load(config)

    provider_registry = ProviderRegistry()
    provider_registry.auto_register()
    auto_register_indicators()

    indicator_registry = IndicatorRegistry()

    async def _run() -> None:
        # Optional PG connection (graceful degradation)
        pg_pool = None
        signal_repo = None
        try:
            from tradecat.data import pg as pg_module  # noqa: PLC0415
            from tradecat.data.repositories import create_repositories  # noqa: PLC0415

            pg_pool = await pg_module.init_pool()
            signal_repo, _ = await create_repositories(pg_pool)
        except Exception:
            pass

        try:
            if timeframe:
                strategy.timeframe = timeframe

            if data:
                from tradecat.core.providers.csv_provider import CsvProvider  # noqa: PLC0415
                p = CsvProvider(data)
            else:
                p = provider_registry.resolve_by_name(provider)
            cooldown_manager = CooldownManager(pg_pool=pg_pool)
            engine = SignalEngine(
                provider_registry,
                indicator_registry,
                cooldown_manager,
                signal_repo,
            )
            signals = await engine.run(strategy, symbol, provider, provider_instance=p)

            for prov in provider_registry.list_providers():
                if hasattr(prov, "close"):
                    try:
                        await prov.close()
                    except Exception:
                        pass

            if output_format == "json":
                click.echo(
                    json.dumps(
                        [s.model_dump() for s in signals],
                        default=str,
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                if not signals:
                    click.echo("无信号触发")
                    return
                click.echo(f"Symbol: {symbol} | Timeframe: {strategy.timeframe}")
                if signal_repo is not None:
                    click.echo(click.style("(PG 持久化已启用)", fg="green"))
                else:
                    click.echo(click.style("(PG 未连接，仅内存模式)", fg="yellow"))
                click.echo("-" * 60)
                for s in signals:
                    click.echo(
                        f"[{s.direction}] {s.rule_name} | 强度:{s.strength} | {s.message}"
                    )
        except (ValueError, KeyError, FileNotFoundError) as e:
            raise click.ClickException(str(e))
        except Exception as e:
            raise click.ClickException(f"Signal engine error: {e}")
        finally:
            if pg_pool is not None:
                try:
                    from tradecat.data import pg as pg_module  # noqa: PLC0415

                    await pg_module.close_pool()
                except Exception:
                    pass

    asyncio.run(_run())
