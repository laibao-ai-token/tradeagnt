"""connector sub-command: manage exchange/wallet connectors."""
from __future__ import annotations

import asyncio
import os

import click

from tradecat.core.connectors import ConnectorRegistry, ExchangeConnector, WalletConnector


def _auto_registry() -> ConnectorRegistry:
    """Auto-register connectors from environment variables."""
    reg = ConnectorRegistry()

    # Try exchange from env vars
    exchange_id = os.getenv("TRADE_EXCHANGE", "binance")
    api_key = os.getenv("TRADE_API_KEY", "")
    secret = os.getenv("TRADE_SECRET", "")
    sandbox = os.getenv("TRADE_SANDBOX", "1") in ("1", "true", "yes")

    if api_key and secret:
        reg.register(
            "default",
            ExchangeConnector(
                name="default",
                exchange_id=exchange_id,
                api_key=api_key,
                secret=secret,
                sandbox=sandbox,
            ),
        )
    return reg


@click.command(name="connector")
@click.option("--list", "list_cmd", is_flag=True, help="列出所有连接器")
@click.option("--connect", help="连接指定连接器名称")
@click.option("--disconnect", help="断开指定连接器名称")
@click.option("--health", help="健康检查指定连接器名称")
@click.option("--exchange", default="binance", help="交易所ID (用于自动注册)")
@click.option("--sandbox/--live", default=True, help="沙盒/实盘模式")
def connector_cmd(
    list_cmd: bool,
    connect: str | None,
    disconnect: str | None,
    health: str | None,
    exchange: str,
    sandbox: bool,
) -> None:
    """管理交易所和钱包连接器生命周期."""

    async def _run() -> None:
        reg = _auto_registry()

        if list_cmd:
            infos = reg.list_info()
            if not infos:
                click.echo("无已注册连接器")
                return
            click.echo(f"{'Name':<15}{'Type':<20}{'Status':<15}")
            click.echo("-" * 50)
            for info in infos:
                color = {
                    "connected": "green",
                    "connecting": "yellow",
                    "error": "red",
                }.get(info.status.value, "white")
                click.echo(
                    click.style(
                        f"{info.name:<15}{info.type:<20}{info.status.value:<15}",
                        fg=color,
                    )
                )
            return

        if connect:
            c = reg.get(connect)
            if not c:
                # Auto-create a named connector on demand
                c = ExchangeConnector(
                    name=connect,
                    exchange_id=exchange,
                    sandbox=sandbox,
                )
                reg.register(connect, c)
            click.echo(f"Connecting {connect}...")
            try:
                await c.connect()
                click.echo(click.style(f"✓ {connect} connected", fg="green"))
            except Exception as e:
                click.echo(click.style(f"✗ {connect} failed: {e}", fg="red"))
            return

        if disconnect:
            c = reg.get(disconnect)
            if not c:
                raise click.ClickException(f"Connector {disconnect} not found")
            await c.disconnect()
            click.echo(click.style(f"✓ {disconnect} disconnected", fg="green"))
            return

        if health:
            c = reg.get(health)
            if not c:
                raise click.ClickException(f"Connector {health} not found")
            ok = await c.health_check()
            if ok:
                click.echo(click.style(f"✓ {health} healthy", fg="green"))
            else:
                click.echo(click.style(f"✗ {health} unhealthy", fg="red"))
            return

        click.echo("Use --list, --connect, --disconnect, or --health")

    asyncio.run(_run())
