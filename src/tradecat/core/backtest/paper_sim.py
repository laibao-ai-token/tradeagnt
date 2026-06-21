"""Simple paper PnL simulation from historical signals (crypto + US equity)."""
from __future__ import annotations

from datetime import datetime
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
    entry_ts: datetime | None = None
    trades: list[dict] = []
    realized = Decimal("0")
    equity_curve: list[Decimal] = [cash]
    closed_pnls: list[Decimal] = []
    hold_minutes: list[float] = []

    def minutes_between(start: datetime | None, end: datetime | None) -> float | None:
        if start is None or end is None:
            return None
        seconds = (end - start).total_seconds()
        if seconds < 0:
            return None
        return seconds / 60.0

    def mark_nav(price: Decimal | None = None) -> Decimal:
        nav_value = cash
        if position_sym and position_qty > 0 and entry_price > 0:
            mark_price = price if price is not None and price > 0 else entry_price
            nav_value += position_qty * mark_price
        return nav_value

    def append_nav(price: Decimal | None = None) -> None:
        equity_curve.append(mark_nav(price))

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
        ts = sig.timestamp

        if direction == "BUY":
            if position_sym and position_sym != sym and position_qty > 0:
                pnl = (price - entry_price) * position_qty
                realized += pnl
                cash += pnl
                closed_pnls.append(pnl)
                held = minutes_between(entry_ts, ts)
                if held is not None:
                    hold_minutes.append(held)
                trades.append(
                    {
                        "symbol": position_sym,
                        "side": "CLOSE",
                        "price": float(price),
                        "pnl": float(pnl),
                        "hold_minutes": held,
                        "ts": ts.isoformat(),
                    }
                )
                position_qty = Decimal("0")
                entry_ts = None
                append_nav(price)
            if position_sym == sym and position_qty > 0:
                append_nav(price)
                continue
            qty = (notional / price).quantize(Decimal("0.000001"))
            if qty <= 0 or cash < notional * Decimal("0.1"):
                append_nav(price)
                continue
            position_sym = sym
            position_qty = qty
            entry_price = price
            entry_ts = ts
            cash -= notional
            trades.append({"symbol": sym, "side": "LONG", "price": float(price), "qty": float(qty), "ts": ts.isoformat()})
            append_nav(price)
        elif direction == "SELL":
            if position_sym == sym and position_qty > 0:
                pnl = (price - entry_price) * position_qty
                realized += pnl
                cash += pnl + notional
                closed_pnls.append(pnl)
                held = minutes_between(entry_ts, ts)
                if held is not None:
                    hold_minutes.append(held)
                trades.append(
                    {
                        "symbol": sym,
                        "side": "CLOSE",
                        "price": float(price),
                        "pnl": float(pnl),
                        "hold_minutes": held,
                        "ts": ts.isoformat(),
                    }
                )
                position_sym = ""
                position_qty = Decimal("0")
                entry_price = Decimal("0")
                entry_ts = None
            append_nav(price)

    nav = cash
    if position_sym and position_qty > 0 and entry_price > 0:
        nav += position_qty * entry_price
    if not equity_curve or equity_curve[-1] != nav:
        equity_curve.append(nav)

    peak = equity_curve[0] if equity_curve else Decimal(str(initial_cash))
    max_drawdown = Decimal("0")
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak * Decimal("100"))

    closed_trade_count = len(closed_pnls)
    winning_trades = sum(1 for pnl in closed_pnls if pnl > 0)
    losing_trades = sum(1 for pnl in closed_pnls if pnl < 0)
    win_rate_pct = (winning_trades / closed_trade_count * 100) if closed_trade_count else None
    avg_hold_minutes = sum(hold_minutes) / len(hold_minutes) if hold_minutes else None
    max_hold_minutes = max(hold_minutes) if hold_minutes else None
    window_minutes = minutes_between(ordered[0].timestamp, ordered[-1].timestamp) if len(ordered) >= 2 else None
    exposure_minutes = sum(hold_minutes)
    if position_sym and entry_ts is not None and len(ordered) >= 1:
        open_held = minutes_between(entry_ts, ordered[-1].timestamp)
        if open_held is not None:
            exposure_minutes += open_held
    exposure_pct = (
        min(100.0, max(0.0, exposure_minutes / window_minutes * 100.0))
        if window_minutes and window_minutes > 0
        else None
    )

    return {
        "market": m,
        "initial_cash": float(initial_cash),
        "notional_per_trade": float(notional_per_trade),
        "signal_count": len(signals),
        "trade_count": len(trades),
        "closed_trade_count": closed_trade_count,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate_pct": float(win_rate_pct) if win_rate_pct is not None else None,
        "max_drawdown_pct": float(max_drawdown),
        "avg_hold_minutes": float(avg_hold_minutes) if avg_hold_minutes is not None else None,
        "max_hold_minutes": float(max_hold_minutes) if max_hold_minutes is not None else None,
        "exposure_minutes": float(exposure_minutes),
        "exposure_pct": float(exposure_pct) if exposure_pct is not None else None,
        "realized_pnl": float(realized),
        "nav": float(nav),
        "return_pct": float((nav - Decimal(str(initial_cash))) / Decimal(str(initial_cash)) * 100),
        "trades": trades[-10:],
        "equity_curve": [float(value) for value in equity_curve],
    }
