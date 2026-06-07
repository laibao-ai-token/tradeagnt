"""submit-thesis orchestration."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from tradecat.agent.audit import append_audit, find_accepted
from tradecat.agent.envelope import Envelope, fail
from tradecat.agent.gates import (
    check_conflict,
    check_risk,
    check_symbol,
    fetch_quote_price,
    gate_snapshot,
)
from tradecat.agent.lock import claim, release
from tradecat.agent.thesis import (
    load_thesis_path,
    load_thesis_stdin,
    thesis_hash,
    thesis_id,
)
from tradecat.agent.engine import get_paper_engine
from tradecat.agent.validate import validate_schema


def _harness_disabled() -> Envelope | None:
    if (os.getenv("TRADEAGNT_HARNESS_V1") or "").strip() in ("1", "true", "yes", "on"):
        return fail("agent_harness_v1_disabled", "TRADEAGNT_HARNESS_V1=1 disables submit-thesis")
    return None


def _resolve_account(engine: PaperTradingEngine, thesis: dict[str, Any]) -> Any:
    intent = thesis.get("paper_intent") if isinstance(thesis.get("paper_intent"), dict) else {}
    account_ref = str(intent.get("account_id") or "").strip()
    if account_ref:
        try:
            acct = engine.get_account(UUID(account_ref))
            if acct:
                return acct
        except Exception:
            pass
    accounts = engine.list_accounts()
    if accounts:
        return accounts[0]
    return engine.create_account("default")


def _write_audit(**kwargs: Any) -> None:
    append_audit(kwargs)


def _audit_reject(
    *,
    tid: str,
    thesis: dict[str, Any],
    gates: dict[str, str],
    err: Envelope,
    thash: str,
    agent_mode: bool,
    warnings: list[str] | None = None,
    **extra: Any,
) -> None:
    _write_audit(
        thesis_id=tid,
        symbol=thesis.get("symbol"),
        direction=thesis.get("direction"),
        outcome="reject",
        error_code=err.error["code"] if err.error else "reject",
        gates=gates,
        thesis_hash=thash,
        agent_mode=agent_mode,
        warnings=warnings,
        **extra,
    )


def submit_thesis(
    *,
    input_path: Path | str | None = None,
    use_stdin: bool = False,
    dry_run: bool = False,
) -> Envelope:
    disabled = _harness_disabled()
    if disabled:
        return disabled

    try:
        if use_stdin:
            thesis = load_thesis_stdin()
        elif input_path:
            thesis = load_thesis_path(input_path)
        else:
            return fail("agent_thesis_load_failed", "provide --input or --stdin")
    except ValueError as exc:
        return fail("agent_thesis_load_failed", str(exc))

    tid = thesis_id(thesis)
    agent_mode = (os.getenv("TRADEAGNT_AGENT_MODE") or "").strip().lower() in ("1", "true", "yes", "on")

    lock_result = claim(tid)
    if not lock_result["acquired"]:
        if lock_result["reason"] == "already_accepted":
            prior = find_accepted(tid)
            fill = (prior or {}).get("fill") or {}
            return Envelope(
                ok=True,
                data={
                    "action": "filled",
                    "idempotent": True,
                    "fill": fill,
                },
                warnings=["idempotent_replay"],
                audit_ref=tid,
            )
        return Envelope(
            ok=True,
            data={"action": "filled", "idempotent": True, "fill": {}},
            warnings=["idempotent_replay", "in_flight"],
            audit_ref=tid,
        )

    accepted = False
    try:
        envelope = _submit_after_claim(
            thesis=thesis,
            tid=tid,
            agent_mode=agent_mode,
            dry_run=dry_run,
        )
        accepted = envelope is not None and envelope.data is not None and envelope.data.get("action") == "filled"
        return envelope
    finally:
        release(tid, accepted=accepted)


def _submit_after_claim(
    *,
    thesis: dict[str, Any],
    tid: str,
    agent_mode: bool,
    dry_run: bool,
) -> Envelope:
    """Gate + engine + audit pipeline. Caller must already hold the claim lock."""
    gates = gate_snapshot()
    warnings: list[str] = []
    thash = thesis_hash(thesis)  # 计算一次，复用

    err = validate_schema(thesis)
    if err:
        gates["schema"] = "fail"
        if not dry_run:
            _audit_reject(tid=tid, thesis=thesis, gates=gates, err=err, thash=thash, agent_mode=agent_mode)
        return err
    gates["schema"] = "pass"

    err = check_risk(thesis)
    if err:
        gates["risk"] = "fail"
        if not dry_run:
            _audit_reject(tid=tid, thesis=thesis, gates=gates, err=err, thash=thash, agent_mode=agent_mode)
        return err
    gates["risk"] = "pass"

    sym_err, symbol, market = check_symbol(thesis)
    if sym_err:
        gates["symbol"] = "fail"
        if not dry_run:
            _audit_reject(tid=tid, thesis=thesis, gates=gates, err=sym_err, thash=thash, agent_mode=agent_mode)
        return sym_err
    gates["symbol"] = "pass"

    direction = str(thesis.get("direction") or "").upper()

    if dry_run:
        gates["conflict"] = "skipped"
        gates["freshness"] = "skipped"
        return Envelope(ok=True, data={"action": "dry_run", "gates": gates}, warnings=warnings, audit_ref=tid)

    if direction == "WATCH_ONLY":
        gates["conflict"] = "pass"
        gates["freshness"] = "pass"
        _write_audit(
            thesis_id=tid, symbol=symbol, market=market, direction=direction,
            outcome="watch_only", error_code=None, gates=gates,
            thesis_hash=thash, agent_mode=agent_mode,
        )
        return Envelope(ok=True, data={"action": "watch_only", "reason": thesis.get("rationale")}, audit_ref=tid)

    engine = get_paper_engine()
    account = _resolve_account(engine, thesis)
    account_id = account.account_id

    conf_err, gates["conflict"], conf_warnings = check_conflict(engine, account_id, symbol, direction)
    warnings.extend(conf_warnings)
    if conf_err:
        if not dry_run:
            _audit_reject(tid=tid, thesis=thesis, gates=gates, err=conf_err, thash=thash, agent_mode=agent_mode, warnings=warnings)
        return conf_err

    price, quote_age_ms, quote_warnings = fetch_quote_price(symbol, market)
    warnings.extend(quote_warnings)
    freshness_sec = int(os.getenv("TRADEAGNT_FRESHNESS_SEC", "60") or "60")
    if quote_age_ms is not None and quote_age_ms > freshness_sec * 1000:
        warnings.append("freshness_warn")
        if (os.getenv("TRADEAGNT_FRESHNESS_STRICT") or "").strip().lower() in ("1", "true", "yes"):
            gates["freshness"] = "fail"
            err = fail("agent_data_stale", f"quote age {quote_age_ms}ms > {freshness_sec}s", gate="freshness", warnings=warnings)
            if not dry_run:
                _audit_reject(tid=tid, thesis=thesis, gates=gates, err=err, thash=thash, agent_mode=agent_mode, warnings=warnings, quote_ts_delta_ms=quote_age_ms)
            return err
    gates["freshness"] = "warn" if "freshness_warn" in warnings else "pass"

    if price is None or price <= 0:
        gates["freshness"] = "fail"
        err = fail("agent_quote_unavailable", "cannot fetch public quote for fill price", gate="freshness", warnings=warnings)
        _audit_reject(tid=tid, thesis=thesis, gates=gates, err=err, thash=thash, agent_mode=agent_mode, warnings=warnings)
        return err

    intent = thesis["paper_intent"]
    margin = Decimal(str(intent["requested_margin_usdt"]))
    leverage = Decimal(str(intent["paper_leverage"]))
    notional = margin * leverage

    if direction == "LONG":
        result = engine.long(account_id, symbol, notional, price, leverage)
    elif direction == "SHORT":
        result = engine.short(account_id, symbol, notional, price, leverage)
    else:
        return fail("agent_thesis_schema_invalid", f"unsupported direction: {direction}", gate="schema")

    if not result.get("ok"):
        msg = str(result.get("error") or "engine rejected order")
        _audit_reject(tid=tid, thesis=thesis, gates=gates, err=fail("agent_engine_reject", msg), thash=thash, agent_mode=agent_mode, warnings=warnings + [msg], engine_tx_note="partial")
        return fail("agent_engine_reject", msg, gate="paper", warnings=warnings)

    order = result.get("order")
    fill_payload = {
        "price": float(price),
        "notional_usdt": float(notional),
        "margin_usdt": float(margin),
        "leverage": float(leverage),
        "order_id": str(order.order_id) if order else None,
        "account_id": str(account_id),
    }
    _write_audit(
        thesis_id=tid, symbol=symbol, market=market, direction=direction,
        outcome="accept", error_code=None, gates=gates,
        thesis_hash=thash, quote_ts_delta_ms=quote_age_ms,
        fill=fill_payload, warnings=warnings, agent_mode=agent_mode,
    )
    return Envelope(ok=True, data={"action": "filled", "fill": fill_payload}, warnings=warnings, audit_ref=tid)


def validate_thesis_only(*, input_path: Path | str | None = None, use_stdin: bool = False) -> Envelope:
    return submit_thesis(input_path=input_path, use_stdin=use_stdin, dry_run=True)
