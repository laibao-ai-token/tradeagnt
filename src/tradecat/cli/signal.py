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
    timeframe: str,
    output_format: str,
) -> None:
    """对指定 symbol 运行策略并输出信号."""
    strategy = StrategyLoader.load(config)

    provider_registry = ProviderRegistry()
    provider_registry.auto_register()
    auto_register_indicators()

    indicator_registry = IndicatorRegistry()
    cooldown_manager = CooldownManager()
    engine = SignalEngine(provider_registry, indicator_registry, cooldown_manager)

    async def _run() -> None:
        try:
            if timeframe:
                strategy.timeframe = timeframe

            p = provider_registry.resolve_by_name(provider)
            signals = await engine.run(strategy, symbol, provider)

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
                click.echo("-" * 60)
                for s in signals:
                    click.echo(
                        f"[{s.direction}] {s.rule_name} | 强度:{s.strength} | {s.message}"
                    )
        except (ValueError, KeyError, FileNotFoundError) as e:
            raise click.ClickException(str(e))
        except Exception as e:
            raise click.ClickException(f"Signal engine error: {e}")

    asyncio.run(_run())
