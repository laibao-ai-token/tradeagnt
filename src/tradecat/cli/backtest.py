"""tradecat backtest sub-command: run strategy against historical data."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import click

from tradecat.core.indicators import auto_register as auto_register_indicators
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals import CooldownManager, SignalEngine, StrategyLoader


@click.command()
@click.option(
    "--mode",
    type=click.Choice(["runner", "offline", "dry"]),
    default="runner",
    help="回测模式: runner=用策略跑历史, offline=模拟离线回放, dry=只计算不判定",
)
@click.option("--strategy", default="default.yaml", help="策略YAML文件路径")
@click.option("--symbol", required=True, help="交易对，如 BTCUSDT")
@click.option("--provider", default="binance", help="数据源提供者")
@click.option("--timeframe", default="1h", help="K线周期")
@click.option("--days", default=30, help="回测最近N天的数据")
@click.option("--min-strength", default=50, help="信号强度阈值")
def backtest(
    mode: str,
    strategy: str,
    symbol: str,
    provider: str,
    timeframe: str,
    days: int,
    min_strength: int,
) -> None:
    """Run backtests: fetch historical data, run signals, output summary."""
    strat = StrategyLoader.load(strategy)
    provider_registry = ProviderRegistry()
    provider_registry.auto_register()
    auto_register_indicators()
    indicator_registry = IndicatorRegistry()

    async def _run() -> None:
        try:
            p = provider_registry.resolve_by_name(provider)

            # Calculate required candle count from days + timeframe
            # 1h ≈ 24 candles/day, 15m ≈ 96 candles/day, 1d ≈ 1 candle/day
            tf_candles_per_day = {
                "1m": 1440, "5m": 288, "15m": 96, "30m": 48,
                "1h": 24, "4h": 6, "1d": 1, "1w": 1/7,
            }
            multiplier = tf_candles_per_day.get(timeframe, 24)
            limit = int(days * multiplier)
            limit = max(limit, 50)  # minimum for indicators

            click.echo(click.style(f"Backtest: {symbol} @ {timeframe}", fg="blue", bold=True))
            click.echo(f"Fetching {limit} candles (~{days} days)...")

            if mode == "offline":
                click.echo("[offline mode] K-line simulation not yet implemented — falling back to runner")
                mode = "runner"

            df = await p.fetch_klines(symbol, timeframe, limit)
            click.echo(f"Loaded {len(df)} rows")

            # Run signal engine
            if strat:
                strat.timeframe = timeframe
                cooldown = CooldownManager()
                engine = SignalEngine(provider_registry, indicator_registry, cooldown)

                # For runner mode, we process the full window as one batch
                signals = await engine.run(strat, symbol, provider)

                # Stats
                buy_signals = [s for s in signals if s.direction == "BUY"]
                sell_signals = [s for s in signals if s.direction == "SELL"]
                strong = [s for s in signals if s.strength >= min_strength]

                click.echo("-" * 60)
                click.echo(click.style("Results", fg="green", bold=True))
                click.echo(f"  Total signals:       {len(signals)}")
                click.echo(f"  BUY:  {len(buy_signals):>4}  |  SELL: {len(sell_signals):>4}")
                click.echo(f"  Strength >= {min_strength}: {len(strong)}")

                if signals:
                    click.echo("-" * 60)
                    click.echo("Last 5 signals:")
                    for s in signals[-5:]:
                        click.echo(f"  [{s.direction}] {s.rule_name} (str={s.strength}) | {s.message}")

            # Close providers
            for prov in provider_registry.list_providers():
                if hasattr(prov, "close"):
                    try:
                        await prov.close()
                    except Exception:
                        pass

        except (ValueError, KeyError, FileNotFoundError) as e:
            raise click.ClickException(str(e))
        except Exception as e:
            raise click.ClickException(f"Backtest error: {e}")

    asyncio.run(_run())
