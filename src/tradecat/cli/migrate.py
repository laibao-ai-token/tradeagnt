"""migrate sub-command: run TimescaleDB/PostgreSQL migrations."""
from __future__ import annotations

import asyncio
from pathlib import Path

import click

from tradecat.data import migrate as migrate_module
from tradecat.data import pg


@click.command(name="migrate")
@click.option(
    "--migrations-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="迁移 SQL 文件目录 (默认: src/tradecat/data/migrations)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="只查看待执行的迁移",
)
def migrate_cmd(migrations_dir: Path | None, dry_run: bool) -> None:
    """执行数据库迁移.\n
    SQL 文件按字母顺序执行，已应用的迁移记录在 schema.migrations 表中。
    """
    if migrations_dir is None:
        migrations_dir = (
            Path(__file__).parent.parent / "data" / "migrations"
        )

    async def _run() -> None:
        try:
            pool = await pg.init_pool()
            runner = migrate_module.MigrationRunner(pool)
            await runner._ensure_tracking()
            applied = await runner._get_applied()
            files = sorted(migrations_dir.glob("*.sql"))

            pending = [f for f in files if f.stem not in applied]

            if dry_run:
                if pending:
                    click.echo("待执行的迁移:")
                    for f in pending:
                        click.echo(f"  - {f.name}")
                else:
                    click.echo("数据库已是最新状态。")
                return

            newly_applied = await runner.run(migrations_dir)
            if newly_applied:
                for name in newly_applied:
                    click.echo(f"Applied: {name}")
            else:
                click.echo("数据库已是最新状态。")
        except Exception as exc:
            raise click.ClickException(f"Migration failed: {exc}")
        finally:
            try:
                await pg.close_pool()
            except Exception:
                pass

    asyncio.run(_run())
