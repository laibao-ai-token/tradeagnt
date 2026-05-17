"""tradecat daemon sub-command: background signal monitoring with optional auto-trade."""
from __future__ import annotations

import asyncio
import os
import signal as sys_signal
from datetime import datetime, timezone
from decimal import Decimal

import click

from tradecat.core.indicators import auto_register as auto_register_indicators
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.paper_trading import PaperTradingEngine
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals import CooldownManager, SignalEngine, StrategyLoader


def _create_paper_engine() -> PaperTradingEngine:
    """Create PaperTradingEngine with SQLite or in-memory repo."""
    repo_type = os.getenv("PAPER_REPO_TYPE", "sqlite")
    if repo_type == "memory":
        from tradecat.core.paper_trading import InMemoryRepository
        repo = InMemoryRepository()
    else:
        from tradecat.core.paper_trading.repository import SqliteRepository
        repo = SqliteRepository()
    return PaperTradingEngine(repo)


def _get_or_create_account(engine: PaperTradingEngine, account_name: str):
    """Get existing account by name, or create a new one."""
    for acct in engine.list_accounts():
        if acct.name == account_name:
            return acct
    return engine.create_account(account_name)


@click.command()
@click.option(
    "--symbols",
    default="BTC_USDT,ETH_USDT",
    help="监控的symbol列表，逗号分隔",
)
@click.option("--strategy", default="default.yaml", help="策略YAML文件路径")
@click.option("--provider", default="gate", help="数据源提供者")
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
@click.option(
    "--auto-trade",
    is_flag=True,
    default=False,
    help="信号触发时自动执行模拟盘交易",
)
@click.option(
    "--notional",
    default=100.0,
    type=float,
    help="每笔交易金额(USDT)，默认100",
)
@click.option(
    "--leverage",
    default=1.0,
    type=float,
    help="杠杆倍数，默认1",
)
@click.option(
    "--account",
    default="default",
    help="模拟盘账户名，默认default",
)
def daemon(
    symbols: str,
    strategy: str,
    provider: str,
    timeframe: str,
    interval: int,
    min_strength: int,
    auto_trade: bool,
    notional: float,
    leverage: float,
    account: str,
) -> None:
    """Run the TradeCat daemon: periodic signal monitoring with optional auto-trade."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    strat = StrategyLoader.load(strategy)
    provider_registry = ProviderRegistry()
    provider_registry.auto_register()
    auto_register_indicators()
    indicator_registry = IndicatorRegistry()

    # Init paper trading engine if auto-trade is enabled
    paper_engine = None
    paper_account = None
    if auto_trade:
        paper_engine = _create_paper_engine()
        paper_account = _get_or_create_account(paper_engine, account)

    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        click.echo(click.style("\n收到终止信号，正在优雅退出...", fg="yellow"))
        shutdown_event.set()

    for sig in (sys_signal.SIGINT, sys_signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, _handle_signal)

    async def _run() -> None:
        cooldown = CooldownManager()
        engine = SignalEngine(provider_registry, indicator_registry, cooldown)
        iteration = 0

        click.echo(click.style("TradeCat Daemon Started", fg="green", bold=True))
        click.echo(f"Symbols: {', '.join(symbol_list)}")
        click.echo(f"Interval: {interval}s | Strategy: {strategy} | Provider: {provider}")
        if auto_trade:
            click.echo(
                click.style(
                    f"Auto-Trade: ON | Notional: {notional} USDT | "
                    f"Leverage: {leverage}x | Account: {paper_account.name}",
                    fg="yellow",
                )
            )
        click.echo("Press Ctrl+C to stop\n")

        try:
            while not shutdown_event.is_set():
                iteration += 1
                now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                click.echo(f"[{iteration:04d}] {now} {click.style('Scanning...', fg='cyan')}")

                for symbol in symbol_list:
                    if shutdown_event.is_set():
                        break
                    try:
                        signals = await engine.run(strat, symbol, provider)
                        strong = [s for s in signals if s.strength >= min_strength]
                        if strong:
                            click.echo(
                                click.style(
                                    f"  ✓ {symbol}: {len(strong)} signal(s)",
                                    fg="green",
                                )
                            )
                            for s in strong:
                                side_tag = f"[{s.direction}]"
                                click.echo(f"    {side_tag} {s.rule_name} | str={s.strength} | {s.message}")

                                # Persist signal to DB for TUI monitoring
                                try:
                                    import sqlite3
                                    from pathlib import Path
                                    signal_db = Path.home() / "pkg/dcu/codex/tradeagnt/libs/database/services/signal-service/signal_history.db"
                                    with sqlite3.connect(str(signal_db)) as conn:
                                        conn.execute(
                                            """INSERT INTO signal_history
                                            (timestamp, symbol, signal_type, direction, strength, price, message, timeframe, source)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                            (
                                                s.timestamp.isoformat() if hasattr(s, "timestamp") and s.timestamp else datetime.now(timezone.utc).isoformat(),
                                                s.symbol,
                                                getattr(s, "rule_id", s.rule_name)[:50],
                                                s.direction,
                                                s.strength,
                                                float(s.price) if hasattr(s, "price") and s.price is not None else 0.0,
                                                (s.message or "")[:200],
                                                strat.timeframe,
                                                "daemon_auto",
                                            ),
                                        )
                                        conn.commit()
                                except Exception:
                                    pass

                                # Auto-trade
                                if auto_trade and paper_engine and paper_account:
                                    if s.direction in ("BUY", "SELL"):
                                        side = "LONG" if s.direction == "BUY" else "SHORT"
                                        price = Decimal(str(s.price))
                                        result = paper_engine.from_signal(
                                            paper_account.account_id,
                                            {
                                                "symbol": s.symbol,
                                                "side": side,
                                                "qty_notional": str(notional),
                                                "leverage": str(leverage),
                                                "idempotency_key": f"{s.rule_id}_{s.timestamp.isoformat()}",
                                            },
                                            price,
                                        )
                                        if result.get("ok"):
                                            click.echo(
                                                click.style(
                                                    f"    → TRADE: {side} {s.symbol} "
                                                    f"@ {price} x{leverage} notional={notional}",
                                                    fg="magenta",
                                                )
                                            )
                                        else:
                                            click.echo(
                                                click.style(
                                                    f"    → SKIP: {result.get('error', 'unknown')}",
                                                    fg="yellow",
                                                )
                                            )
                        else:
                            click.echo(f"  · {symbol}: no signals")
                    except Exception as e:
                        click.echo(f"  ✗ {symbol}: {e}")

                if not shutdown_event.is_set():
                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        pass

        except asyncio.CancelledError:
            pass
        finally:
            for prov in provider_registry.list_providers():
                if hasattr(prov, "close"):
                    try:
                        await prov.close()
                    except Exception:
                        pass
            click.echo(click.style("\nDaemon stopped.", fg="green"))

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
