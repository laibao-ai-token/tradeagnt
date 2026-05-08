"""Paper trading orchestration with guard and execution audit integration."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - import path depends on caller (src package vs script path).
    from src.execution_protocol.models import ExecutionPhase
    from src.execution_protocol.protocol import ExecutionProtocol
    from src.risk import GuardConfig, GuardPipeline
    from src.storage.read_only import fetch_recent_signals
except ImportError:  # pragma: no cover
    from execution_protocol.models import ExecutionPhase
    from execution_protocol.protocol import ExecutionProtocol
    from risk import GuardConfig, GuardPipeline
    from storage.read_only import fetch_recent_signals

from .models import OrderStatus, PaperFill, PaperLedger, PaperOrder, PaperPosition, PortfolioState, Side


class PaperTradingOrchestrator:
    """Coordinate candidate generation, risk checks, execution, and audit trail."""

    def __init__(
        self,
        initial_equity: float = 10000.0,
        guard_config: Optional[GuardConfig] = None,
        artifacts_dir: str | Path | None = None,
        execution_log_dir: str | Path | None = None,
    ):
        self.artifacts_dir = Path(artifacts_dir or "artifacts/paper_trading")
        self.execution_log_dir = Path(execution_log_dir or "artifacts/execution_audit")
        self.ledger = PaperLedger(initial_equity=initial_equity, cash_balance=initial_equity)
        self.peak_equity = initial_equity
        self.guard = GuardPipeline(guard_config or GuardConfig())
        self.protocol = ExecutionProtocol(log_dir=str(self.execution_log_dir))
        self._persisted_total_trades = 0
        self._persisted_open_positions = 0
        self._load_state()

    def _state_file(self) -> Path:
        return self.artifacts_dir / "state.json"

    def _execution_report_file(self) -> Path:
        return self.artifacts_dir / "execution_reports.jsonl"

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def _parse_order_status(value: object) -> OrderStatus:
        if isinstance(value, OrderStatus):
            return value
        try:
            return OrderStatus(str(value))
        except Exception:
            return OrderStatus.PENDING

    @staticmethod
    def _parse_side_enum(value: object) -> Side:
        if isinstance(value, Side):
            return value
        normalized = str(value or "").upper()
        if normalized == Side.LONG.value:
            return Side.LONG
        if normalized == Side.SHORT.value:
            return Side.SHORT
        return Side.NEUTRAL

    def _serialize_order(self, order: PaperOrder) -> dict:
        return {
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": float(order.qty),
            "idempotency_key": order.idempotency_key,
            "entry_price": order.entry_price,
            "entry_ts": order.entry_ts.isoformat() if order.entry_ts else None,
            "entry_score": order.entry_score,
            "entry_reason": order.entry_reason,
            "status": order.status.value,
            "slippage_bps": float(order.slippage_bps),
            "fee": float(order.fee),
            "strategy_label": order.strategy_label,
            "rejected_reason": order.rejected_reason,
        }

    def _deserialize_order(self, payload: object) -> PaperOrder | None:
        if not isinstance(payload, dict):
            return None
        order_id = str(payload.get("order_id") or "").strip()
        symbol = str(payload.get("symbol") or "").strip()
        if not order_id or not symbol:
            return None
        return PaperOrder(
            order_id=order_id,
            symbol=symbol,
            side=self._parse_side_enum(payload.get("side")),
            qty=float(payload.get("qty", 0.0) or 0.0),
            idempotency_key=str(payload.get("idempotency_key") or order_id),
            entry_price=float(payload["entry_price"]) if payload.get("entry_price") is not None else None,
            entry_ts=self._parse_datetime(payload.get("entry_ts")),
            entry_score=int(payload["entry_score"]) if payload.get("entry_score") is not None else None,
            entry_reason=str(payload.get("entry_reason") or "") or None,
            status=self._parse_order_status(payload.get("status")),
            slippage_bps=float(payload.get("slippage_bps", 0.0) or 0.0),
            fee=float(payload.get("fee", 0.0) or 0.0),
            strategy_label=str(payload.get("strategy_label") or "default"),
            rejected_reason=str(payload.get("rejected_reason") or "") or None,
        )

    def _serialize_position(self, position: PaperPosition) -> dict:
        return {
            "symbol": position.symbol,
            "side": position.side.value,
            "qty": float(position.qty),
            "entry_price": float(position.entry_price),
            "entry_ts": position.entry_ts.isoformat(),
            "unrealized_pnl": float(position.unrealized_pnl),
            "realized_pnl": float(position.realized_pnl),
        }

    def _deserialize_position(self, payload: object) -> PaperPosition | None:
        if not isinstance(payload, dict):
            return None
        symbol = str(payload.get("symbol") or "").strip()
        entry_ts = self._parse_datetime(payload.get("entry_ts"))
        if not symbol or entry_ts is None:
            return None
        return PaperPosition(
            symbol=symbol,
            side=self._parse_side_enum(payload.get("side")),
            qty=float(payload.get("qty", 0.0) or 0.0),
            entry_price=float(payload.get("entry_price", 0.0) or 0.0),
            entry_ts=entry_ts,
            unrealized_pnl=float(payload.get("unrealized_pnl", 0.0) or 0.0),
            realized_pnl=float(payload.get("realized_pnl", 0.0) or 0.0),
        )

    def _serialize_fill(self, fill: PaperFill) -> dict:
        return {
            "fill_id": fill.fill_id,
            "order_id": fill.order_id,
            "symbol": fill.symbol,
            "side": fill.side.value,
            "qty": float(fill.qty),
            "price": float(fill.price),
            "slippage_bps": float(fill.slippage_bps),
            "fee": float(fill.fee),
            "ts": fill.ts.isoformat(),
        }

    def _deserialize_fill(self, payload: object) -> PaperFill | None:
        if not isinstance(payload, dict):
            return None
        fill_id = str(payload.get("fill_id") or "").strip()
        order_id = str(payload.get("order_id") or "").strip()
        symbol = str(payload.get("symbol") or "").strip()
        ts = self._parse_datetime(payload.get("ts"))
        if not fill_id or not order_id or not symbol or ts is None:
            return None
        return PaperFill(
            fill_id=fill_id,
            order_id=order_id,
            symbol=symbol,
            side=self._parse_side_enum(payload.get("side")),
            qty=float(payload.get("qty", 0.0) or 0.0),
            price=float(payload.get("price", 0.0) or 0.0),
            slippage_bps=float(payload.get("slippage_bps", 0.0) or 0.0),
            fee=float(payload.get("fee", 0.0) or 0.0),
            ts=ts,
        )

    def _load_state(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        state_file = self._state_file()
        if not state_file.exists():
            return
        try:
            with state_file.open(encoding="utf-8") as f:
                data = json.load(f)
            self.ledger.initial_equity = float(data.get("initial_equity", self.ledger.initial_equity))
            self.ledger.cash_balance = float(
                data.get("cash_balance", data.get("current_equity", self.ledger.cash_balance))
            )
            self.ledger.realized_pnl = float(data.get("realized_pnl", self.ledger.realized_pnl))
            self.peak_equity = float(data.get("peak_equity", max(self.ledger.initial_equity, self.ledger.cash_balance)))
            self._persisted_total_trades = int(data.get("total_trades", 0) or 0)
            self._persisted_open_positions = int(data.get("open_positions", 0) or 0)
            orders: dict[str, PaperOrder] = {}
            for item in data.get("orders", []):
                order = self._deserialize_order(item)
                if order is not None:
                    orders[order.order_id] = order
            if orders:
                self.ledger.orders = orders
            positions: dict[str, PaperPosition] = {}
            for item in data.get("positions", []):
                position = self._deserialize_position(item)
                if position is not None:
                    positions[position.symbol] = position
            if positions:
                self.ledger.positions = positions
            fills: list[PaperFill] = []
            for item in data.get("fills", []):
                fill = self._deserialize_fill(item)
                if fill is not None:
                    fills.append(fill)
            if fills:
                self.ledger.fills = fills
            cooldown_payload = data.get("cooldown", {})
            if isinstance(cooldown_payload, dict):
                for symbol, ts in cooldown_payload.items():
                    parsed = self._parse_datetime(ts)
                    if parsed is not None:
                        self.guard.record_trade(str(symbol), ts=parsed)
        except Exception:
            # Keep defaults if state is corrupted.
            return

    def _save_state(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        state_file = self._state_file()
        report = self.get_execution_report_summary(limit=10000)
        total_trades = max(len(self.ledger.fills), self._persisted_total_trades, int(report.get("filled", 0)))
        open_positions = len(self.ledger.positions)
        self._persisted_total_trades = total_trades
        self._persisted_open_positions = open_positions
        cooldown_cache = getattr(self.guard, "_cooldown_cache", {})
        cooldown_payload = {
            symbol: ts.isoformat()
            for symbol, ts in cooldown_cache.items()
            if isinstance(symbol, str) and isinstance(ts, datetime)
        }
        with state_file.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "schema_version": "2.0",
                    "initial_equity": self.ledger.initial_equity,
                    "cash_balance": self.ledger.cash_balance,
                    "current_equity": self.ledger.cash_balance,
                    "realized_pnl": self.ledger.realized_pnl,
                    "peak_equity": self.peak_equity,
                    "total_trades": total_trades,
                    "open_positions": open_positions,
                    "orders": [self._serialize_order(order) for order in self.ledger.orders.values()],
                    "positions": [self._serialize_position(position) for position in self.ledger.positions.values()],
                    "fills": [self._serialize_fill(fill) for fill in self.ledger.fills],
                    "cooldown": cooldown_payload,
                },
                f,
            )

    @staticmethod
    def _to_float(value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _load_execution_reports(self, limit: int | None = None) -> list[dict]:
        report_file = self._execution_report_file()
        if not report_file.exists():
            return []
        try:
            lines = report_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        if limit is not None and limit > 0:
            lines = lines[-int(limit) :]
        payloads = []
        for line in lines:
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except Exception:
                continue
            if isinstance(item, dict):
                payloads.append(item)
        return payloads

    def _append_execution_report(self, record: dict) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        report_file = self._execution_report_file()
        with report_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _build_execution_attribution(
        self,
        *,
        order: PaperOrder,
        trace_id: str,
        guard_result: dict,
        execution_price: float,
        fill_price: float,
        slippage_bps: float,
        fee: float,
        outcome: str,
        error_code: str | None = None,
        error: str | None = None,
    ) -> dict:
        qty = abs(float(order.qty))
        requested_price = float(execution_price)
        filled_price = float(fill_price)
        requested_notional = qty * requested_price
        filled_notional = qty * filled_price
        slippage_cost = qty * abs(filled_price - requested_price)
        net_cash_impact = 0.0
        if outcome == "FILLED":
            if order.side == Side.LONG:
                net_cash_impact = -(filled_notional + float(fee))
            elif order.side == Side.SHORT:
                net_cash_impact = filled_notional - float(fee)

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "order_id": order.order_id,
            "trace_id": trace_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": qty,
            "requested_price": requested_price,
            "fill_price": filled_price,
            "requested_notional": requested_notional,
            "filled_notional": filled_notional,
            "slippage_bps": float(slippage_bps),
            "slippage_cost": float(slippage_cost),
            "fee": float(fee),
            "net_cash_impact": float(net_cash_impact),
            "outcome": outcome,
            "guard_passed": bool(guard_result.get("passed")),
            "guard_risk_level": guard_result.get("risk_level"),
            "guard_failed_rules": list(guard_result.get("failed_rules") or []),
            "guard_reasons": list(guard_result.get("reasons") or []),
            "error_code": error_code,
            "error": error,
        }

    @staticmethod
    def _parse_side(side: str) -> Side:
        normalized = str(side or "").upper()
        if normalized == "LONG":
            return Side.LONG
        if normalized == "SHORT":
            return Side.SHORT
        return Side.NEUTRAL

    @staticmethod
    def _guard_result_to_dict(result: object) -> dict:
        return {
            "passed": bool(getattr(result, "passed", False)),
            "risk_level": getattr(result, "risk_level", "low"),
            "reasons": list(getattr(result, "reasons", []) or []),
            "failed_rules": list(getattr(result, "failed_rules", []) or []),
            "checked_rules": list(getattr(result, "checked_rules", []) or []),
            "checked_at": (
                getattr(result, "checked_at", None).isoformat() if getattr(result, "checked_at", None) else None
            ),
        }

    def _current_positions_pct(self) -> dict[str, float]:
        return {pos.symbol: abs(pos.qty) for pos in self.ledger.get_all_positions()}

    @staticmethod
    def _order_ts(order: PaperOrder) -> float:
        if isinstance(order.entry_ts, datetime):
            return order.entry_ts.timestamp()
        return 0.0

    def _find_order_by_idempotency_key(self, key: str, *, include_finalized: bool) -> PaperOrder | None:
        normalized = str(key or "").strip()
        if not normalized:
            return None
        finalized = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
        matches = []
        for order in self.ledger.orders.values():
            if order.idempotency_key != normalized:
                continue
            if not include_finalized and order.status in finalized:
                continue
            matches.append(order)
        if not matches:
            return None
        matches.sort(key=lambda order: (self._order_ts(order), order.order_id), reverse=True)
        return matches[0]

    def generate_candidate(
        self,
        symbol: str,
        side: str,
        size_pct: float,
        score: int,
        reason: str,
        *,
        idempotency_key: str | None = None,
        reuse_finalized: bool = False,
    ) -> PaperOrder:
        normalized_side = self._parse_side(side)
        key = idempotency_key or f"{symbol}:{normalized_side.value}:{size_pct:.6f}:{score}:{reason}"
        existing = self._find_order_by_idempotency_key(key, include_finalized=reuse_finalized)
        if existing is not None:
            return existing
        order_id = f"order_{uuid.uuid4().hex[:12]}"
        order = PaperOrder(
            order_id=order_id,
            symbol=symbol,
            side=normalized_side,
            qty=float(size_pct),
            idempotency_key=key,
            entry_ts=datetime.now(timezone.utc),
            entry_score=score,
            entry_reason=reason,
        )
        self.ledger.add_order(order)
        self._save_state()
        return order

    def generate_candidate_from_latest_signal(
        self,
        symbol: str,
        *,
        timeframe: str | None = None,
        size_pct: float = 0.10,
        min_strength: int = 50,
        db_path: str | Path | None = None,
    ) -> dict:
        """Generate a candidate order from latest read-only signal data."""
        try:
            rows = fetch_recent_signals(
                db_path=db_path,
                symbol=symbol,
                timeframe=timeframe,
                limit=1,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "signal_source_unavailable",
                "error": f"failed to read signal source: {exc}",
            }
        if not rows:
            return {
                "ok": False,
                "error_code": "signal_not_found",
                "error": f"no signal found for symbol={symbol} timeframe={timeframe or 'any'}",
            }

        row = rows[0]
        direction = str(row.direction or "").upper()
        if direction == "BUY":
            side = "LONG"
        elif direction == "SELL":
            side = "SHORT"
        else:
            return {
                "ok": False,
                "error_code": "unsupported_signal_direction",
                "error": f"unsupported signal direction: {direction}",
                "signal": row.to_dict(),
            }

        if int(row.strength) < int(min_strength):
            return {
                "ok": False,
                "error_code": "signal_strength_too_low",
                "error": f"signal strength {row.strength} below min_strength {min_strength}",
                "signal": row.to_dict(),
            }

        order = self.generate_candidate(
            symbol=row.symbol,
            side=side,
            size_pct=size_pct,
            score=int(row.strength),
            reason=f"signal:{row.signal_type}:{row.direction}",
            idempotency_key=f"signal:{row.id}",
            reuse_finalized=True,
        )
        return {
            "ok": True,
            "order": order,
            "signal": row.to_dict(),
        }

    def _build_portfolio_state(self, mark_prices: dict[str, float] | None = None) -> PortfolioState:
        mark_prices = mark_prices or {}
        position_market_value = 0.0
        unrealized_pnl = 0.0

        for position in self.ledger.get_all_positions():
            mark_price = float(mark_prices.get(position.symbol, position.entry_price))
            qty = abs(float(position.qty))
            if position.side == Side.LONG:
                pnl = (mark_price - float(position.entry_price)) * qty
            elif position.side == Side.SHORT:
                pnl = (float(position.entry_price) - mark_price) * qty
            else:
                pnl = 0.0

            market_value = qty * mark_price
            position.mark_price = mark_price
            position.market_value = market_value
            position.unrealized_pnl = pnl
            unrealized_pnl += pnl
            position_market_value += market_value

        total_equity = float(self.ledger.cash_balance) + position_market_value
        peak_equity = max(float(self.peak_equity), total_equity)
        drawdown_pct = 0.0
        if peak_equity > 0:
            drawdown_pct = (peak_equity - total_equity) / peak_equity
        self.peak_equity = peak_equity
        return_pct = 0.0
        if self.ledger.initial_equity > 0:
            return_pct = (total_equity - self.ledger.initial_equity) / self.ledger.initial_equity * 100

        return PortfolioState(
            initial_equity=float(self.ledger.initial_equity),
            cash_balance=float(self.ledger.cash_balance),
            position_market_value=float(position_market_value),
            unrealized_pnl=float(unrealized_pnl),
            realized_pnl=float(self.ledger.realized_pnl),
            total_equity=float(total_equity),
            peak_equity=float(self.peak_equity),
            drawdown_pct=float(drawdown_pct),
            open_positions=len(self.ledger.positions),
            return_pct=float(return_pct),
        )

    def get_portfolio_state(self, mark_prices: dict[str, float] | None = None) -> dict:
        state = self._build_portfolio_state(mark_prices=mark_prices)
        return {
            "initial_equity": state.initial_equity,
            "cash_balance": state.cash_balance,
            "position_market_value": state.position_market_value,
            "unrealized_pnl": state.unrealized_pnl,
            "realized_pnl": state.realized_pnl,
            "total_equity": state.total_equity,
            "peak_equity": state.peak_equity,
            "drawdown_pct": state.drawdown_pct,
            "open_positions": state.open_positions,
            "return_pct": state.return_pct,
        }

    def validate(
        self,
        symbol: str,
        side: str,
        size_pct: float,
        *,
        last_signal_ts: datetime | None = None,
    ) -> dict:
        portfolio_state = self.get_portfolio_state()
        result = self.guard.validate_trade_intent(
            symbol=symbol,
            side=side,
            size_pct=size_pct,
            current_positions=self._current_positions_pct(),
            current_equity=portfolio_state["total_equity"],
            peak_equity=portfolio_state["peak_equity"],
            last_signal_ts=last_signal_ts,
        )
        freshness = self.guard.validate_data_freshness(last_signal_ts)
        drawdown = self.guard.validate_drawdown(
            current_equity=portfolio_state["total_equity"],
            peak_equity=portfolio_state["peak_equity"],
        )
        payload = self._guard_result_to_dict(result)
        payload["subchecks"] = {
            "data_freshness": self._guard_result_to_dict(freshness),
            "max_drawdown": self._guard_result_to_dict(drawdown),
        }
        return payload

    def dry_run(
        self,
        symbol: str,
        side: str,
        size_pct: float,
        execution_price: float,
        score: int = 80,
        reason: str = "dry_run",
        *,
        last_signal_ts: datetime | None = None,
    ) -> dict:
        guard_result = self.validate(symbol, side, size_pct, last_signal_ts=last_signal_ts)
        slippage = float(execution_price) * 2.0 / 10000
        fee = float(execution_price) * 0.0004
        return {
            "mode": "dry_run",
            "symbol": symbol,
            "side": side,
            "qty": size_pct,
            "score": score,
            "reason": reason,
            "estimated_price": execution_price,
            "estimated_slippage": slippage,
            "estimated_fee": fee,
            "guard": guard_result,
        }

    def _apply_cash_impact(self, side: Side, qty: float, price: float, fee: float) -> None:
        notional = abs(qty) * price
        if side == Side.LONG:
            self.ledger.cash_balance -= notional + fee
        elif side == Side.SHORT:
            self.ledger.cash_balance += notional - fee

    def confirm_and_execute(
        self,
        order_id: str,
        execution_price: float,
        slippage_bps: float = 2.0,
        fee_rate: float = 0.0004,
        *,
        last_signal_ts: datetime | None = None,
    ) -> dict:
        order = self.ledger.orders.get(order_id)
        if order is None:
            return {"success": False, "error_code": "order_not_found", "error": "order not found", "retriable": False}
        if order.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return {
                "success": False,
                "error_code": "order_finalized",
                "error": f"order already finalized: {order.status.value}",
                "retriable": False,
            }

        state = self.protocol.start_execution(
            intent_id=order.idempotency_key,
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side.value,
            size_pct=order.qty,
        )
        trace_id = state.trace_id

        guard_result = self.validate(
            symbol=order.symbol,
            side=order.side.value,
            size_pct=order.qty,
            last_signal_ts=last_signal_ts,
        )
        self.protocol.validate(trace_id, guard_result["passed"], reasons=guard_result["reasons"])
        if not guard_result["passed"]:
            self.ledger.transition_order(
                order_id,
                OrderStatus.REJECTED,
                rejected_reason="; ".join(guard_result["reasons"]) or "guard validation failed",
            )
            self._save_state()
            audit = self.protocol.replay(trace_id)
            attribution = self._build_execution_attribution(
                order=order,
                trace_id=trace_id,
                guard_result=guard_result,
                execution_price=float(execution_price),
                fill_price=float(execution_price),
                slippage_bps=0.0,
                fee=0.0,
                outcome="REJECTED",
                error_code="guard_validation_failed",
                error="guard validation failed",
            )
            self._append_execution_report(attribution)
            return {
                "success": False,
                "error_code": "guard_validation_failed",
                "error": "guard validation failed",
                "retriable": False,
                "guard": guard_result,
                "trace_id": trace_id,
                "audit": audit,
                "attribution": attribution,
            }

        if order.status == OrderStatus.PENDING:
            if not self.ledger.transition_order(order_id, OrderStatus.STAGED):
                self.protocol.fail(trace_id, ExecutionPhase.STAGE, "failed to stage order")
                return {
                    "success": False,
                    "error_code": "stage_failed",
                    "error": "failed to stage order",
                    "retriable": True,
                    "trace_id": trace_id,
                    "audit": self.protocol.replay(trace_id),
                }
        self.protocol.stage(trace_id)

        if order.status == OrderStatus.STAGED:
            if not self.ledger.transition_order(order_id, OrderStatus.CONFIRMED):
                self.protocol.fail(trace_id, ExecutionPhase.CONFIRM, "failed to confirm order")
                return {
                    "success": False,
                    "error_code": "confirm_failed",
                    "error": "failed to confirm order",
                    "retriable": True,
                    "trace_id": trace_id,
                    "audit": self.protocol.replay(trace_id),
                }
        self.protocol.confirm(trace_id)

        slippage = float(execution_price) * slippage_bps / 10000
        actual_price = (
            float(execution_price) + slippage if order.side == Side.LONG else float(execution_price) - slippage
        )
        fee = abs(order.qty) * float(execution_price) * fee_rate

        self.protocol.execute(trace_id, actual_price)
        if not self.ledger.fill_order(order_id, actual_price, slippage_bps, fee):
            self.protocol.fail(trace_id, ExecutionPhase.EXECUTE, "failed to fill order")
            return {
                "success": False,
                "error_code": "fill_failed",
                "error": "failed to fill order",
                "retriable": True,
                "trace_id": trace_id,
                "audit": self.protocol.replay(trace_id),
            }

        self._apply_cash_impact(order.side, order.qty, actual_price, fee)
        self._build_portfolio_state()
        self.guard.record_trade(order.symbol)
        self.protocol.sync(trace_id)
        self._save_state()
        audit = self.protocol.replay(trace_id)
        attribution = self._build_execution_attribution(
            order=order,
            trace_id=trace_id,
            guard_result=guard_result,
            execution_price=float(execution_price),
            fill_price=actual_price,
            slippage_bps=slippage_bps,
            fee=fee,
            outcome="FILLED",
        )
        self._append_execution_report(attribution)

        return {
            "success": True,
            "order_id": order_id,
            "trace_id": trace_id,
            "fill_price": actual_price,
            "slippage": slippage,
            "fee": fee,
            "guard": guard_result,
            "audit": audit,
            "attribution": attribution,
            "retriable": False,
        }

    def confirm_and_execute_with_retry(
        self,
        order_id: str,
        execution_price: float,
        *,
        max_retries: int = 2,
        slippage_bps: float = 2.0,
        fee_rate: float = 0.0004,
        last_signal_ts: datetime | None = None,
    ) -> dict:
        """Execute order with bounded retry semantics for retriable failures."""
        attempts = max(1, int(max_retries) + 1)
        last_result: dict | None = None
        for attempt in range(1, attempts + 1):
            result = self.confirm_and_execute(
                order_id=order_id,
                execution_price=execution_price,
                slippage_bps=slippage_bps,
                fee_rate=fee_rate,
                last_signal_ts=last_signal_ts,
            )
            result["attempt"] = attempt
            result["max_attempts"] = attempts
            if result.get("success"):
                return result
            last_result = result
            if not result.get("retriable"):
                break

        if last_result is None:
            return {
                "success": False,
                "error_code": "execution_not_started",
                "error": "execution not started",
                "retriable": False,
                "attempt": 0,
                "max_attempts": attempts,
            }
        return last_result

    def get_positions(self) -> list[dict]:
        positions = []
        for pos in self.ledger.get_all_positions():
            positions.append(
                {
                    "symbol": pos.symbol,
                    "side": pos.side.value,
                    "qty": pos.qty,
                    "entry_price": pos.entry_price,
                    "entry_ts": pos.entry_ts.isoformat(),
                }
            )
        return positions

    def get_execution_report_summary(self, *, limit: int = 200) -> dict:
        records = self._load_execution_reports(limit=max(1, int(limit)))
        summary = {
            "records": len(records),
            "filled": 0,
            "rejected": 0,
            "failed": 0,
            "total_fee": 0.0,
            "total_slippage_cost": 0.0,
            "net_cash_impact": 0.0,
            "symbols": {},
            "latest": records[-1] if records else None,
            "report_file": str(self._execution_report_file()),
        }

        for item in records:
            outcome = str(item.get("outcome") or "").upper()
            symbol = str(item.get("symbol") or "UNKNOWN")
            symbol_bucket = summary["symbols"].setdefault(
                symbol,
                {
                    "records": 0,
                    "filled": 0,
                    "rejected": 0,
                    "failed": 0,
                    "total_fee": 0.0,
                    "total_slippage_cost": 0.0,
                    "net_cash_impact": 0.0,
                },
            )

            symbol_bucket["records"] += 1
            symbol_bucket["total_fee"] += self._to_float(item.get("fee"))
            symbol_bucket["total_slippage_cost"] += self._to_float(item.get("slippage_cost"))
            symbol_bucket["net_cash_impact"] += self._to_float(item.get("net_cash_impact"))

            summary["total_fee"] += self._to_float(item.get("fee"))
            summary["total_slippage_cost"] += self._to_float(item.get("slippage_cost"))
            summary["net_cash_impact"] += self._to_float(item.get("net_cash_impact"))

            if outcome == "FILLED":
                summary["filled"] += 1
                symbol_bucket["filled"] += 1
            elif outcome == "REJECTED":
                summary["rejected"] += 1
                symbol_bucket["rejected"] += 1
            else:
                summary["failed"] += 1
                symbol_bucket["failed"] += 1

        return summary

    def get_stats(self) -> dict:
        attribution = self.get_execution_report_summary(limit=200)
        total_trades = max(len(self.ledger.fills), self._persisted_total_trades, int(attribution.get("filled", 0)))
        portfolio_state = self.get_portfolio_state()

        return {
            "initial_equity": portfolio_state["initial_equity"],
            "cash_balance": portfolio_state["cash_balance"],
            "position_market_value": portfolio_state["position_market_value"],
            "unrealized_pnl": portfolio_state["unrealized_pnl"],
            "realized_pnl": portfolio_state["realized_pnl"],
            "total_equity": portfolio_state["total_equity"],
            "current_equity": portfolio_state["total_equity"],
            "peak_equity": portfolio_state["peak_equity"],
            "drawdown_pct": portfolio_state["drawdown_pct"],
            "total_trades": total_trades,
            "open_positions": portfolio_state["open_positions"],
            "return_pct": portfolio_state["return_pct"],
            "attribution": attribution,
        }
