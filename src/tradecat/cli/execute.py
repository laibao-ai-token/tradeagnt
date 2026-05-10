"""execute sub-command: signal → order pipeline."""
from __future__ import annotations

import asyncio
import json

import click

from tradecat.core.indicators import auto_register as auto_register_indicators
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.models.order import Order
from tradecat.core.orders import OrderService
from tradecat.core.orders.risk import RiskManager
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals import CooldownManager, SignalEngine, StrategyLoader
from tradecat.data import pg
from tradecat.data.repositories import create_repositories


@click.command(name="execute")
@click.option("--config", required=True, help="策略YAML文件路径")
@click.option("--symbol", required=True, help="交易对")
@click.option("--provider", default="binance", help="数据源提供者")
@click.option("--timeframe", default="1h", help="K线周期")
@click.option(
    "--min-strength",
    default=50,
    type=int,
    help="最小信号强度阈值",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="只生成订单不实际发送",
)
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["json", "table"]),
    default="table",
    help="输出格式",
)
def execute_cmd(
    config: str,
    symbol: str,
    provider: str,
    timeframe: str,
    min_strength: int,
    dry_run: bool,
    output_format: str,
) -> None:
    """运行策略 → 生成信号 → 转换为订单.

    完整的 signal → order pipeline，支持 --dry-run 模式。
    """
    strategy = StrategyLoader.load(config)
    provider_registry = ProviderRegistry()
    provider_registry.auto_register()
    auto_register_indicators()
    indicator_registry = IndicatorRegistry()

    async def _run() -> None:
        # Optional PG (graceful degradation)
        pg_pool = None
        signal_repo = None
        try:
            pg_pool = await pg.init_pool()
            signal_repo, _ = await create_repositories(pg_pool)
        except Exception:
            pass

        try:
            if timeframe:
                strategy.timeframe = timeframe

            cooldown_manager = CooldownManager(pg_pool=pg_pool)
            engine = SignalEngine(
                provider_registry,
                indicator_registry,
                cooldown_manager,
                signal_repo,
            )
            signals = await engine.run(strategy, symbol, provider)

            # Close providers
            for prov in provider_registry.list_providers():
                if hasattr(prov, "close"):
                    try:
                        await prov.close()
                    except Exception:
                        pass

            # Signal → Order conversion
            risk = RiskManager(min_strength=min_strength)
            svc = OrderService(risk_manager=risk)
            orders = svc.create_orders_from_signals(signals)

            # Output
            if output_format == "json":
                click.echo(
                    json.dumps(
                        [o.model_dump() for o in orders],
                        default=str,
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                click.echo(click.style(f"Strategy: {config}", fg="blue", bold=True))
                click.echo(f"Symbol: {symbol} | Timeframe: {strategy.timeframe}")
                click.echo(f"Signals generated: {len(signals)}  →  Orders: {len(orders)}")
                if dry_run:
                    click.echo(click.style("【DRY RUN - 未实际发送】", fg="yellow"))
                if pg_pool:
                    click.echo(click.style("(PG 持久化已启用)", fg="green"))
                click.echo("-" * 60)
                click.echo(svc.format_dry_run(orders))

        except (ValueError, KeyError, FileNotFoundError) as e:
            raise click.ClickException(str(e))
        except Exception as e:
            raise click.ClickException(f"Execute pipeline error: {e}")
        finally:
            if pg_pool is not None:
                try:
                    await pg.close_pool()
                except Exception:
                    pass

    asyncio.run(_run())
