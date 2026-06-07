"""tradecat agent — thesis submit, validate, paper-report (E3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from tradecat.agent.report import build_paper_report
from tradecat.agent.submit import submit_thesis, validate_thesis_only


def _emit(envelope) -> None:
    click.echo(envelope.to_json())


@click.group(name="agent")
def agent() -> None:
    """Agent harness: thesis gates + paper trading writes."""


@agent.command(name="submit-thesis")
@click.option("--input", "input_path", type=click.Path(path_type=Path), help="Path to thesis JSON")
@click.option("--stdin", "use_stdin", is_flag=True, help="Read thesis JSON from stdin")
def submit_cmd(input_path: Path | None, use_stdin: bool) -> None:
    """Validate thesis and submit to paper engine (fail-closed)."""
    if not use_stdin and not input_path:
        raise click.ClickException("Provide --input <path> or --stdin")
    env = submit_thesis(input_path=input_path, use_stdin=use_stdin, dry_run=False)
    _emit(env)


@agent.command(name="thesis-validate")
@click.option("--input", "input_path", type=click.Path(path_type=Path), help="Path to thesis JSON")
@click.option("--stdin", "use_stdin", is_flag=True, help="Read thesis JSON from stdin")
def validate_cmd(input_path: Path | None, use_stdin: bool) -> None:
    """Dry-run gates only; no paper write, no audit."""
    if not use_stdin and not input_path:
        raise click.ClickException("Provide --input <path> or --stdin")
    env = validate_thesis_only(input_path=input_path, use_stdin=use_stdin)
    _emit(env)


@agent.command(name="paper-report")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON envelope")
@click.option("--symbol", default="", help="Filter recent rejects by symbol")
@click.option("--include-rejects", default=5, show_default=True, type=int)
def paper_report_cmd(as_json: bool, symbol: str, include_rejects: int) -> None:
    """Paper account status and recent agent rejects."""
    env = build_paper_report(symbol=symbol or None, include_rejects=include_rejects)
    if as_json:
        _emit(env)
        return
    if not env.ok or not env.data:
        click.echo(json.dumps(env.to_dict(), indent=2))
        return
    d = env.data
    click.echo(f"Account: {d.get('account_name')} ({d.get('account_id')})")
    click.echo(f"NAV: {d.get('nav')}  PnL: {d.get('pnl')} ({d.get('pnl_pct')}%)")
    click.echo(f"Positions: {len(d.get('positions') or [])}")
    for row in d.get("recent_rejects") or []:
        click.echo(f"  reject {row.get('thesis_id')}: {row.get('error_code')}")


@agent.command(name="audit-tail")
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--symbol", default="")
def audit_tail_cmd(limit: int, symbol: str) -> None:
    """Print recent audit rows as JSON array."""
    from tradecat.agent.audit import tail_audit

    rows = tail_audit(limit=limit, symbol=symbol or None)
    click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
