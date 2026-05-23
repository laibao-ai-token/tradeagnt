"""tradecat backtest sub-command: run strategy against historical data."""
from __future__ import annotations

import asyncio

import click

from tradecat.core.backtest.paper_sim import simulate_paper_trades
from tradecat.core.indicators import auto_register as auto_register_indicators
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals import CooldownManager, SignalEngine, StrategyLoader
from tradecat.core.symbols import (
    default_provider_for_market,
    normalize_market,
    normalize_symbol,
    signal_symbol_for_engine,
)


@click.command()
@click.option(
    "--mode",
    type=click.Choice(["runner", "scan", "dry"]),
    default="scan",
    help="runner=最新K线判定, scan=全历史扫描, dry=只拉数据",
)
@click.option("--strategy", default="default.yaml", help="策略YAML文件路径")
@click.option("--symbol", required=True, help="标的，如 BTC_USDT 或 NVDA")
@click.option("--provider", default="", help="数据源（留空则按策略 market 自动选择）")
@click.option("--timeframe", default="", help="K线周期（留空则用策略文件）")
@click.option("--days", default=5, help="回测最近N天（影响拉取 bar 数量上限）")
@click.option("--min-strength", default=50, help="信号强度阈值")
@click.option("--initial-cash", default=10000.0, type=float, help="模拟盘初始资金")
@click.option("--notional", default=1000.0, type=float, help="每笔模拟交易名义金额")
@click.option("--paper/--no-paper", default=True, help="是否输出简易模拟盘 PnL")
def backtest(
    mode: str,
    strategy: str,
    symbol: str,
    provider: str,
    timeframe: str,
    days: int,
    min_strength: int,
    initial_cash: float,
    notional: float,
    paper: bool,
) -> None:
    """Run backtests: fetch historical data, run signals, optional paper PnL summary."""
    strat = StrategyLoader.load(strategy)
    market = normalize_market(strat.market)
    norm_symbol = normalize_symbol(symbol, market)
    if not norm_symbol:
        raise click.ClickException(f"Invalid symbol for market {market}: {symbol}")

    run_symbol = signal_symbol_for_engine(norm_symbol, market)
    provider_name = (provider or "").strip() or default_provider_for_market(market)
    tf = (timeframe or strat.timeframe or "5m").strip()
    strat.timeframe = tf

    provider_registry = ProviderRegistry()
    provider_registry.auto_register()
    auto_register_indicators()
    indicator_registry = IndicatorRegistry()

    async def _run() -> None:
        try:
            p = provider_registry.resolve_by_name(provider_name)

            tf_candles_per_day = {
                "1m": 390,
                "5m": 78,
                "15m": 26,
                "30m": 13,
                "1h": 7,
                "1d": 1,
            }
            multiplier = tf_candles_per_day.get(tf, 78 if market == "us_stock" else 24)
            limit = max(50, int(days * multiplier))
            if market == "us_stock":
                limit = min(limit, 390)

            click.echo(click.style(f"Backtest [{market}]: {norm_symbol} @ {tf}", fg="blue", bold=True))
            click.echo(f"Provider: {provider_name} | Fetching up to {limit} bars (~{days}d)...")

            df = await p.fetch_klines(run_symbol, tf, limit)
            click.echo(f"Loaded {len(df)} rows")

            if mode == "dry":
                if len(df) > 0:
                    last = df.iloc[-1]
                    click.echo(f"Last close: {last.get('close', 'N/A')}")
                return

            cooldown = CooldownManager()
            engine = SignalEngine(provider_registry, indicator_registry, cooldown)

            if mode == "runner":
                signals = await engine.run(strat, run_symbol, provider_name, provider_instance=p)
            else:
                signals = await engine.scan_history(
                    strat,
                    run_symbol,
                    provider_name,
                    provider_instance=p,
                    min_strength=float(min_strength),
                )

            buy_signals = [s for s in signals if s.direction == "BUY"]
            sell_signals = [s for s in signals if s.direction == "SELL"]
            strong = [s for s in signals if s.strength >= min_strength]

            click.echo("-" * 60)
            click.echo(click.style("Signal Results", fg="green", bold=True))
            click.echo(f"  Total signals:       {len(signals)}")
            click.echo(f"  BUY:  {len(buy_signals):>4}  |  SELL: {len(sell_signals):>4}")
            click.echo(f"  Strength >= {min_strength}: {len(strong)}")

            if strong:
                click.echo("-" * 60)
                click.echo("Last 5 signals:")
                for s in strong[-5:]:
                    click.echo(f"  [{s.direction}] {s.rule_name} (str={s.strength}) | {s.message}")

            if paper and strong:
                summary = simulate_paper_trades(
                    strong,
                    market=market,
                    initial_cash=initial_cash,
                    notional_per_trade=notional,
                    min_strength=min_strength,
                )
                click.echo("-" * 60)
                click.echo(click.style("Paper Simulation", fg="magenta", bold=True))
                click.echo(f"  Trades:        {summary['trade_count']}")
                click.echo(f"  Realized PnL:  {summary['realized_pnl']:.2f}")
                click.echo(f"  NAV:           {summary['nav']:.2f}")
                click.echo(f"  Return:        {summary['return_pct']:.2f}%")
                currency = "USD" if market == "us_stock" else "USDT"
                click.echo(f"  (notional={notional} {currency} per trade)")

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
