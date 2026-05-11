"""tradecat paper sub-command: virtual paper trading."""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import UUID

import click

from tradecat.core.paper_trading import InMemoryRepository, PaperTradingEngine, Side


@click.group(name="paper")
def paper() -> None:
    """Paper trading — simulate orders, positions, and P&L."""
    pass


# ─── Helpers ───

_ENGINE_CACHE = None

def _engine() -> PaperTradingEngine:
    """初始化 PaperTradingEngine，默认 SQLite 持久化."""
    global _ENGINE_CACHE
    if _ENGINE_CACHE is not None:
        return _ENGINE_CACHE
    repo_type = os.getenv("PAPER_REPO_TYPE", "sqlite")
    if repo_type == "memory":
        repo = InMemoryRepository()
    else:
        from tradecat.core.paper_trading.repository import SqliteRepository
        repo = SqliteRepository()
    _ENGINE_CACHE = PaperTradingEngine(repo)
    return _ENGINE_CACHE


def _get_account(engine, account_id):
    """获取账户：优先用传入的 ID，否则取第一个，都没有则自动创建 default."""
    if account_id:
        return engine.get_account(__import__("uuid").UUID(account_id))
    accounts = list(engine._repo._accounts.keys())
    if accounts:
        return engine.get_account(accounts[0])
    return engine.create_account("default")


def _fmt_decimal(d: Decimal) -> str:
    return f"{d:.6f}".rstrip("0").rstrip(".")


# ─── Account ───

@paper.group(name="account")
def account() -> None:
    """Manage paper accounts."""
    pass


@account.command(name="create")
@click.option("--name", default="default", help="Account name")
@click.option("--balance", default="10000", help="Initial balance")
@click.option("--leverage", default="1", help="Default leverage")
def account_create(name: str, balance: str, leverage: str) -> None:
    """Create a new paper trading account."""
    engine = _engine()
    acct = engine.create_account(name, Decimal(balance), Decimal(leverage))
    click.echo(click.style("✓ Account created", fg="green"))
    click.echo(f"  ID:    {acct.account_id}")
    click.echo(f"  Name:  {acct.name}")
    click.echo(f"  Balance: {balance} USDT")
    click.echo(f"  Leverage: {leverage}x")


@account.command(name="list")
def account_list() -> None:
    """List all paper accounts."""
    click.echo("(Account listing via PG query — implement in P2)")


# ─── Order entry ───

@paper.command(name="long")
@click.option("--account-id", help="Account UUID (omit to use default)")
@click.option("--notional", required=True, help="Notional value in USDT")
@click.option("--price", required=True, help="Entry price")
@click.option("--leverage", default="1", help="Leverage multiplier")
@click.argument("symbol")
def long_cmd(symbol: str, account_id: str | None, notional: str, price: str, leverage: str) -> None:
    """Open a LONG position."""
    engine = _engine()
    acct = _get_account(engine, account_id)
    if not acct:
        # Auto-create default account on first use
        acct = engine.create_account("default")
    result = engine.long(acct.account_id, symbol.upper(), Decimal(notional), Decimal(price), Decimal(leverage))
    if result["ok"]:
        o = result["order"]
        click.echo(click.style(f"✓ LONG {symbol}", fg="green"))
        click.echo(f"  Qty: {_fmt_decimal(o.qty)} @ {price}")
        click.echo(f"  Order: {o.order_id}")
    else:
        click.echo(click.style(f"✗ Rejected: {result['error']}", fg="red"))


@paper.command(name="short")
@click.option("--account-id", help="Account UUID")
@click.option("--notional", required=True, help="Notional value in USDT")
@click.option("--price", required=True, help="Entry price")
@click.option("--leverage", default="1", help="Leverage multiplier")
@click.argument("symbol")
def short_cmd(symbol: str, account_id: str | None, notional: str, price: str, leverage: str) -> None:
    """Open a SHORT position."""
    engine = _engine()
    acct = _get_account(engine, account_id)
    if not acct:
        acct = engine.create_account("default")
    result = engine.short(acct.account_id, symbol.upper(), Decimal(notional), Decimal(price), Decimal(leverage))
    if result["ok"]:
        o = result["order"]
        click.echo(click.style(f"✓ SHORT {symbol}", fg="green"))
        click.echo(f"  Qty: {_fmt_decimal(o.qty)} @ {price}")
        click.echo(f"  Order: {o.order_id}")
    else:
        click.echo(click.style(f"✗ Rejected: {result['error']}", fg="red"))


@paper.command(name="close")
@click.option("--account-id", help="Account UUID")
@click.option("--price", required=True, help="Close price")
@click.argument("symbol")
def close_cmd(symbol: str, account_id: str | None, price: str) -> None:
    """Close an existing position."""
    engine = _engine()
    acct = _get_account(engine, account_id)
    if not acct:
        raise click.ClickException("No account found. Create one with: tradecat paper account create")
    result = engine.close(acct.account_id, symbol.upper(), Decimal(price))
    if result["ok"]:
        p = result["position"]
        click.echo(click.style(f"✓ Closed {symbol}", fg="green"))
        click.echo(f"  Realized PnL: {_fmt_decimal(p.realized_pnl)}")
    else:
        click.echo(click.style(f"✗ {result['error']}", fg="yellow"))


@paper.command(name="flip")
@click.option("--account-id", help="Account UUID")
@click.option("--notional", required=True, help="New position notional")
@click.option("--price", required=True, help="Flip price")
@click.option("--leverage", default="1", help="Leverage")
@click.argument("symbol")
def flip_cmd(symbol: str, account_id: str | None, notional: str, price: str, leverage: str) -> None:
    """Close existing position and flip to opposite side."""
    engine = _engine()
    acct = _get_account(engine, account_id)
    if not acct:
        raise click.ClickException("No account found.")
    result = engine.flip(acct.account_id, symbol.upper(), Decimal(notional), Decimal(price), Decimal(leverage))
    if result["ok"]:
        click.echo(click.style(f"✓ Flipped {symbol}", fg="green"))
    else:
        click.echo(click.style(f"✗ {result['error']}", fg="red"))


# ─── Queries ───

@paper.command(name="status")
@click.option("--account-id", help="Account UUID")
def status_cmd(account_id: str | None) -> None:
    """Show account status, positions, and recent orders."""
    engine = _engine()
    acct = _get_account(engine, account_id)
    if not acct:
        raise click.ClickException("No account found.")
    st = engine.status(acct.account_id)
    click.echo(click.style(f"📊 {acct.name}", fg="blue", bold=True))
    click.echo(f"Balance:      {_fmt_decimal(acct.balance)} USDT")
    click.echo(f"Total Equity: {_fmt_decimal(st['total_equity'])} USDT")
    click.echo(f"Drawdown:     {st['drawdown_pct']}%")
    click.echo("-" * 40)
    if st["positions"]:
        click.echo("Positions:")
        for p in st["positions"]:
            click.echo(f"  {p.side.value:<6} {p.symbol:<10} {_fmt_decimal(p.qty):>12} @ {_fmt_decimal(p.entry_price)}")
    else:
        click.echo("No open positions")


@paper.command(name="history")
@click.option("--account-id", help="Account UUID")
@click.option("--limit", default=20, help="Recent orders limit")
def history_cmd(account_id: str | None, limit: int) -> None:
    """Show recent order history."""
    engine = _engine()
    acct = _get_account(engine, account_id)
    if not acct:
        raise click.ClickException("No account found.")
    orders = engine.history(acct.account_id, limit)
    click.echo(click.style(f"Recent orders (last {limit})", fg="blue"))
    for o in orders:
        color = "green" if o.status.value == "FILLED" else "yellow" if o.status.value == "REJECTED" else "white"
        click.echo(click.style(f"  [{o.status.value:<10}] {o.side.value:<6} {o.symbol:<10} {_fmt_decimal(o.qty):>12}", fg=color))


@paper.command(name="positions")
@click.option("--account-id", help="Account UUID")
def positions_cmd(account_id: str | None) -> None:
    """List open positions."""
    status_cmd(account_id)


@paper.command(name="portfolio")
@click.option("--account-id", help="Account UUID")
def portfolio_cmd(account_id: str | None) -> None:
    """Show portfolio overview."""
    status_cmd(account_id)


@paper.command(name="stats")
@click.option("--account-id", help="Account UUID")
def stats_cmd(account_id: str | None) -> None:
    """Show trading statistics."""
    engine = _engine()
    acct = _get_account(engine, account_id)
    if not acct:
        raise click.ClickException("No account found.")
    s = engine.stats(acct.account_id)
    click.echo(click.style("📈 Stats", fg="blue", bold=True))
    for k, v in s.items():
        click.echo(f"  {k:<15} {v}")


@paper.command(name="from-signal")
@click.option("--account-id", help="Account UUID")
@click.option("--price", required=True, help="Current market price")
@click.option("--side", required=True, type=click.Choice(["LONG", "SHORT"]), help="Signal side")
@click.option("--notional", help="Override notional value")
@click.option("--idempotency-key", help="Deduplication key")
@click.argument("symbol")
def from_signal_cmd(
    symbol: str,
    account_id: str | None,
    price: str,
    side: str,
    notional: str | None,
    idempotency_key: str | None,
) -> None:
    """Execute a signal-derived order."""
    engine = _engine()
    acct = _get_account(engine, account_id)
    if not acct:
        acct = engine.create_account("default")
    payload = {
        "symbol": symbol.upper(),
        "side": side,
        "qty_notional": notional or "0",
        "idempotency_key": idempotency_key or f"{symbol}_{side}_{price}",
    }
    result = engine.from_signal(acct.account_id, payload, Decimal(price))
    if result["ok"]:
        click.echo(click.style(f"✓ Signal order filled", fg="green"))
    else:
        click.echo(click.style(f"✗ {result['error']}", fg="red"))
