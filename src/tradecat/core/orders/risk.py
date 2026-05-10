"""Risk management for order generation."""
from __future__ import annotations

from tradecat.core.models.order import Order, OrderSide
from tradecat.core.signals.models import SignalEvent


class RiskManager:
    """Simple risk controls before converting signals to orders."""

    def __init__(
        self,
        min_strength: int = 50,
        max_daily_orders: int = 10,
        default_qty: float = 0.01,
    ) -> None:
        self.min_strength = min_strength
        self.max_daily_orders = max_daily_orders
        self.default_qty = default_qty
        self._daily_count: dict[str, int] = {}  # symbol -> count

    def validate_signal(self, signal: SignalEvent) -> bool:
        """Check if a signal passes risk filters."""
        # 1. Only actionable directions
        if signal.direction not in ("BUY", "SELL"):
            return False

        # 2. Minimum strength
        if signal.strength < self.min_strength:
            return False

        # 3. Daily order limit per symbol
        symbol = signal.symbol
        if self._daily_count.get(symbol, 0) >= self.max_daily_orders:
            return False

        return True

    def calculate_position_size(self, signal: SignalEvent) -> float:
        """Return base position size (simplified; real impl uses account balance)."""
        _ = signal  # future: scale by signal strength / account size
        return self.default_qty

    def record_order(self, symbol: str) -> None:
        """Increment daily order counter for a symbol."""
        self._daily_count[symbol] = self._daily_count.get(symbol, 0) + 1

    def from_signal(self, signal: SignalEvent) -> Order | None:
        """Convert a signal to an order if it passes risk checks."""
        if not self.validate_signal(signal):
            return None

        side = OrderSide.BUY if signal.direction == "BUY" else OrderSide.SELL
        qty = self.calculate_position_size(signal)
        self.record_order(signal.symbol)

        return Order(
            symbol=signal.symbol,
            side=side,
            qty=qty,
            signal_id=signal.rule_id,
            signal_name=signal.rule_name,
            metadata={"signal_strength": signal.strength, "signal_price": signal.price},
        )
