"""tradecat daemon sub-command: background signal monitoring."""
from __future__ import annotations

import asyncio
import signal as sys_signal

import click

from tradecat.core.indicators import auto_register as auto_register_indicators
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals import CooldownManager, SignalEngine, StrategyLoader


@click.command()
@click.option(
    "--symbols",
    default="BTCUSDT,ETHUSDT",
    help="监控的symbol列表，逗号分隔",
)
@click.option("--strategy", default="default.yaml", help="策略YAML文件路径")
@click.option("--provider", default="binance", help="数据源提供者")
@click.option("--timeframe", default="1h", help="K线周期")
@click.option(
    "--interval",
    default=300,
    type=int,
    help="检查间隔秒数（默认300=5分钟）",
)
@click.option(
    "--min-strength",
    default=50,
    type=int,
    help="最小信号强度阈值",
)
def daemon(
    symbols: str,
    strategy: str,
    provider: str,
    timeframe: str,
    interval: int,
    min_strength: int,
) -> None:
    """Run the TradeCat daemon: periodic signal monitoring in background."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    strat = StrategyLoader.load(strategy)
    provider_registry = ProviderRegistry()
    provider_registry.auto_register()
    auto_register_indicators()
    indicator_registry = IndicatorRegistry()

    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        click.echo(click.style("\n收到终止信号，正在优雅退出...", fg="yellow"))
        shutdown_event.set()

    # Register OS signals for graceful shutdown
    for sig in (sys_signal.SIGINT, sys_signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, _handle_signal)

    async def _run() -> None:
        cooldown = CooldownManager()
        engine = SignalEngine(provider_registry, indicator_registry, cooldown)
        iteration = 0

        click.echo(click.style("🔁 TradeCat Daemon Started", fg="green", bold=True))
        click.echo(f"Symbols: {', '.join(symbol_list)}")
        click.echo(f"Interval: {interval}s | Strategy: {strategy}")
        click.echo("Press Ctrl+C to stop\n")

        try:
            while not shutdown_event.is_set():
                iteration += 1
                click.echo(f"[{iteration:04d}] {click.style('Scanning...', fg='cyan')}")

                for symbol in symbol_list:
                    if shutdown_event.is_set():
                        break
                    try:
                        signals = await engine.run(strat, symbol, provider)
                        strong = [s for s in signals if s.strength >= min_strength]
                        if strong:
                            click.echo(
                                click.style(
                                    f"  ✓ {symbol}: {len(strong)} strong signal(s)",
                                    fg="green",
                                )
                            )
                            for s in strong:
                                click.echo(f"    [{s.direction}] {s.rule_name} | {s.message}")
                        else:
                            click.echo(f"  · {symbol}: no signals")
                    except Exception as e:
                        click.echo(f"  ✗ {symbol}: {e}")

                # Close providers between iterations
                for prov in provider_registry.list_providers():
                    if hasattr(prov, "close"):
                        try:
                            await prov.close()
                        except Exception:
                            pass

                if not shutdown_event.is_set():
                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        pass

        except asyncio.CancelledError:
            pass
        finally:
            click.echo(click.style("\nDaemon stopped.", fg="green"))

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
