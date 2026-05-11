"""tradecat analyze sub-command: comprehensive symbol analysis."""
from __future__ import annotations

import asyncio

import click

from tradecat.core.indicators import auto_register as auto_register_indicators
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals import CooldownManager, SignalEngine, StrategyLoader


@click.command()
@click.option("--symbol", required=True, help="Symbol to analyze, e.g. BTCUSDT")
@click.option("--provider", default="binance", help="数据源提供者")
@click.option("--timeframe", default="1h", help="K线周期")
@click.option("--strategy", default="default.yaml", help="策略YAML文件路径")
@click.option("--limit", default=100, help="K线条数")
def analyze(
    symbol: str,
    provider: str,
    timeframe: str,
    strategy: str,
    limit: int,
) -> None:
    """Fetch market data, run indicators & signals, and print a comprehensive report."""
    provider_registry = ProviderRegistry()
    provider_registry.auto_register()
    auto_register_indicators()
    indicator_registry = IndicatorRegistry()

    async def _run() -> None:
        try:
            p = provider_registry.resolve_by_name(provider)
            df = await p.fetch_klines(symbol, timeframe, limit)

            # Load strategy (graceful fallback to default)
            try:
                strat = StrategyLoader.load(strategy)
            except FileNotFoundError:
                click.echo(click.style(f"Strategy {strategy} not found, using in-memory defaults", fg="yellow"))
                strat = None

            # Run indicators
            indicators = indicator_registry.list()
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else None

            # Header
            click.echo(click.style(f"📊 {symbol} @ {timeframe}", fg="blue", bold=True))
            click.echo(f"Data points: {len(df)} | Price: {latest.get('close', 'N/A')}")
            click.echo("-" * 60)

            # Indicator summary
            for ind_name, meta in indicators.items():
                try:
                    result = meta.func(df.copy(), **meta.params)
                    last_row = result.iloc[-1]
                    # Extract key column(s) added by this indicator
                    added_cols = [c for c in result.columns if c not in df.columns]
                    vals = {c: last_row.get(c, "N/A") for c in added_cols[:3]}
                    val_str = " | ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}" for k, v in vals.items())
                    click.echo(f"  {ind_name:<20} {val_str}")
                except Exception as e:
                    click.echo(f"  {ind_name:<20} [error: {e}]")

            # Signals
            if strat:
                cooldown = CooldownManager()
                engine = SignalEngine(provider_registry, indicator_registry, cooldown)
                signals = await engine.run(strat, symbol, provider)
                click.echo("-" * 60)
                click.echo(click.style(f"Signals: {len(signals)}", fg="green" if signals else "yellow"))
                for s in signals:
                    click.echo(f"  [{s.direction}] {s.rule_name} (strength={s.strength}) | {s.message}")

            # Close providers
            for prov in provider_registry.list_providers():
                if hasattr(prov, "close"):
                    try:
                        await prov.close()
                    except Exception:
                        pass

        except (ValueError, KeyError) as e:
            raise click.ClickException(str(e))
        except Exception as e:
            raise click.ClickException(f"Analysis error: {e}")

    asyncio.run(_run())
