"""Merge duplicate crypto positions (e.g. BTCUSDT + BTC_USDT)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from tradecat.core.paper_trading.models import PaperPosition, Side
from tradecat.core.symbols.crypto import normalize_crypto_pair


def _signed_qty(pos: PaperPosition) -> Decimal:
    if pos.qty <= 0 or pos.side == Side.NEUTRAL:
        return Decimal("0")
    return pos.qty if pos.side == Side.LONG else -pos.qty


def _merge_position_group(account_id, symbol: str, group: list[PaperPosition]) -> PaperPosition:
    realized = sum((p.realized_pnl for p in group), Decimal("0"))
    unrealized = sum((p.unrealized_pnl for p in group), Decimal("0"))
    leverage = group[0].leverage
    updated_at = max((p.updated_at for p in group), default=datetime.utcnow())

    net = Decimal("0")
    for p in group:
        net += _signed_qty(p)

    if net == 0:
        return PaperPosition(
            account_id=account_id,
            symbol=symbol,
            side=Side.NEUTRAL,
            qty=Decimal("0"),
            entry_price=Decimal("0"),
            margin=Decimal("0"),
            leverage=leverage,
            unrealized_pnl=unrealized,
            realized_pnl=realized,
            updated_at=updated_at,
        )

    side = Side.LONG if net > 0 else Side.SHORT
    net_qty = abs(net)

    cost = Decimal("0")
    for p in group:
        sign = Decimal("1") if p.side == Side.LONG else Decimal("-1")
        cost += sign * p.qty * p.entry_price

    entry = abs(cost / net) if net != 0 else Decimal("0")
    margin = net_qty * entry / leverage if leverage else net_qty * entry

    return PaperPosition(
        account_id=account_id,
        symbol=symbol,
        side=side,
        qty=net_qty,
        entry_price=entry,
        margin=margin,
        leverage=leverage,
        unrealized_pnl=unrealized,
        realized_pnl=realized,
        updated_at=updated_at,
    )


def consolidate_crypto_positions(positions: list[PaperPosition]) -> list[PaperPosition]:
    """Return one row per normalized crypto pair (non-zero qty only)."""
    active = [p for p in positions if p.qty and p.qty > 0]
    if not active:
        return []

    groups: dict[str, list[PaperPosition]] = defaultdict(list)
    for p in active:
        key = normalize_crypto_pair(p.symbol) or p.symbol.strip().upper()
        groups[key].append(p)

    merged: list[PaperPosition] = []
    for sym, group in sorted(groups.items()):
        merged.append(_merge_position_group(group[0].account_id, sym, group))
    return [p for p in merged if p.qty > 0]


def consolidate_positions_in_repo(repo, account_id) -> int:
    """Persist merged positions; zero out legacy duplicate symbol rows."""
    from uuid import UUID

    aid = account_id if isinstance(account_id, UUID) else UUID(str(account_id))
    raw = repo.list_positions(aid)
    active = [p for p in raw if p.qty and p.qty > 0]
    if not active:
        return 0

    groups: dict[str, list[PaperPosition]] = defaultdict(list)
    for p in active:
        key = normalize_crypto_pair(p.symbol) or p.symbol.strip().upper()
        groups[key].append(p)

    changed = 0
    for sym, group in groups.items():
        merged = _merge_position_group(aid, sym, group)
        repo.upsert_position(merged)
        changed += 1
        for p in group:
            if p.symbol != sym:
                cleared = PaperPosition(
                    account_id=aid,
                    symbol=p.symbol,
                    side=Side.NEUTRAL,
                    qty=Decimal("0"),
                    entry_price=Decimal("0"),
                    margin=Decimal("0"),
                    leverage=p.leverage,
                    unrealized_pnl=Decimal("0"),
                    realized_pnl=Decimal("0"),
                    updated_at=datetime.utcnow(),
                )
                repo.upsert_position(cleared)
                changed += 1
    return changed
