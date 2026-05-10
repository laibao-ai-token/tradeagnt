"""Order service: transform signals into executable orders."""
from __future__ import annotations

from tradecat.core.models.order import Order
from tradecat.core.orders.risk import RiskManager
from tradecat.core.signals.models import SignalEvent


class OrderService:
    """Orchestrates the signal → order conversion pipeline."""

    def __init__(self, risk_manager: RiskManager | None = None) -> None:
        self.risk = risk_manager or RiskManager()

    def create_orders_from_signals(self, signals: list[SignalEvent]) -> list[Order]:
        """Convert a batch of signals into orders after risk checks."""
        orders: list[Order] = []
        for sig in signals:
            order = self.risk.from_signal(sig)
            if order is not None:
                orders.append(order)
        return orders

    def format_dry_run(self, orders: list[Order]) -> str:
        """Return human-readable dry-run output."""
        if not orders:
            return "No orders generated (all signals rejected by risk controls)."
        lines = [f"Generated {len(orders)} order(s):", ""]
        for i, o in enumerate(orders, 1):
            lines.append(
                f"  {i}. [{o.side.value}] {o.symbol} | qty={o.qty} "
                f"| type={o.order_type.value} | from signal: {o.signal_name}"
            )
        return "\n".join(lines)
