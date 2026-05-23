"""Simple paper PnL simulation from historical signals (crypto + US equity)."""
from __future__ import annotations

from decimal import Decimal

from tradecat.core.signals.models import SignalEvent
from tradecat.core.symbols import normalize_market, normalize_symbol


def simulate_paper_trades(
    signals: list[SignalEvent],
    *,
    market: str,
    initial_cash: float = 10_000.0,
    notional_per_trade: float = 1_000.0,
    min_strength: int = 50,
) -> dict:
    """Long-only flip on BUY/SELL for demo backtest summary."""
    m = normalize_market(market)
    cash = Decimal(str(initial_cash))
    notional = Decimal(str(notional_per_trade))
    position_sym = ""
    position_qty = Decimal("0")
    entry_price = Decimal("0")
    trades: list[dict] = []
    realized = Decimal("0")

    ordered = sorted(signals, key=lambda s: s.timestamp)
    for sig in ordered:
        if int(sig.strength) < min_strength:
            continue
        sym = normalize_symbol(sig.symbol, m) or sig.symbol.strip().upper()
        if not sym:
            continue
        direction = (sig.direction or "").strip().upper()
        price = Decimal(str(sig.price or 0))
        if price <= 0:
            continue

        if direction == "BUY":
            if position_sym and position_sym != sym and position_qty > 0:
                pnl = (price - entry_price) * position_qty
                realized += pnl
                cash += pnl
                trades.append({"symbol": position_sym, "side": "CLOSE", "price": float(price), "pnl": float(pnl)})
                position_qty = Decimal("0")
            if position_sym == sym and position_qty > 0:
                continue
            qty = (notional / price).quantize(Decimal("0.000001"))
            if qty <= 0 or cash < notional * Decimal("0.1"):
                continue
            position_sym = sym
            position_qty = qty
            entry_price = price
            cash -= notional
            trades.append({"symbol": sym, "side": "LONG", "price": float(price), "qty": float(qty)})
        elif direction == "SELL":
            if position_sym == sym and position_qty > 0:
                pnl = (price - entry_price) * position_qty
                realized += pnl
                cash += pnl + notional
                trades.append({"symbol": sym, "side": "CLOSE", "price": float(price), "pnl": float(pnl)})
                position_sym = ""
                position_qty = Decimal("0")
                entry_price = Decimal("0")

    nav = cash
    if position_sym and position_qty > 0 and entry_price > 0:
        nav += position_qty * entry_price

    return {
        "market": m,
        "initial_cash": float(initial_cash),
        "notional_per_trade": float(notional_per_trade),
        "signal_count": len(signals),
        "trade_count": len(trades),
        "realized_pnl": float(realized),
        "nav": float(nav),
        "return_pct": float((nav - Decimal(str(initial_cash))) / Decimal(str(initial_cash)) * 100),
        "trades": trades[-10:],
    }
