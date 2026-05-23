"""Paper trading repository — abstract base + SQLite + in-memory implementations."""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any
from uuid import UUID

from tradecat.core.paper_trading.models import (
    OrderStatus,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PortfolioSnapshot,
    Side,
)


class BaseRepository(ABC):
    """Abstract storage for paper trading entities."""

    @abstractmethod
    def create_account(self, account: PaperAccount) -> PaperAccount: ...

    @abstractmethod
    def get_account(self, account_id: UUID) -> PaperAccount | None: ...

    @abstractmethod
    def list_accounts(self) -> list[PaperAccount]: ...

    @abstractmethod
    def create_order(self, order: PaperOrder) -> PaperOrder: ...

    @abstractmethod
    def get_order(self, order_id: UUID) -> PaperOrder | None: ...

    @abstractmethod
    def get_order_by_idempotency(self, key: str) -> PaperOrder | None: ...

    @abstractmethod
    def update_order_status(self, order_id: UUID, status: OrderStatus) -> None: ...

    @abstractmethod
    def list_orders(self, account_id: UUID, symbol: str | None = None, limit: int = 100) -> list[PaperOrder]: ...

    @abstractmethod
    def upsert_position(self, position: PaperPosition) -> None: ...

    @abstractmethod
    def get_position(self, account_id: UUID, symbol: str) -> PaperPosition | None: ...

    @abstractmethod
    def list_positions(self, account_id: UUID) -> list[PaperPosition]: ...

    @abstractmethod
    def record_fill(self, fill: PaperFill) -> None: ...

    @abstractmethod
    def list_fills(self, account_id: UUID, symbol: str | None = None, limit: int = 100) -> list[PaperFill]: ...

    @abstractmethod
    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None: ...

    @abstractmethod
    def get_latest_snapshot(self, account_id: UUID) -> PortfolioSnapshot | None: ...


class InMemoryRepository(BaseRepository):
    """In-memory repository for testing / quick iteration."""

    def __init__(self) -> None:
        self._accounts: dict[UUID, PaperAccount] = {}
        self._orders: dict[UUID, PaperOrder] = {}
        self._orders_by_idempotency: dict[str, UUID] = {}
        self._positions: dict[tuple[UUID, str], PaperPosition] = {}
        self._fills: list[PaperFill] = []
        self._snapshots: list[PortfolioSnapshot] = []

    def create_account(self, account: PaperAccount) -> PaperAccount:
        self._accounts[account.account_id] = account
        return account

    def get_account(self, account_id: UUID) -> PaperAccount | None:
        return self._accounts.get(account_id)

    def list_accounts(self) -> list[PaperAccount]:
        return list(self._accounts.values())

    def create_order(self, order: PaperOrder) -> PaperOrder:
        self._orders[order.order_id] = order
        if order.idempotency_key:
            self._orders_by_idempotency[order.idempotency_key] = order.order_id
        return order

    def get_order(self, order_id: UUID) -> PaperOrder | None:
        return self._orders.get(order_id)

    def get_order_by_idempotency(self, key: str) -> PaperOrder | None:
        oid = self._orders_by_idempotency.get(key)
        return self._orders.get(oid) if oid else None

    def update_order_status(self, order_id: UUID, status: OrderStatus) -> None:
        if order := self._orders.get(order_id):
            order.status = status
            order.updated_at = __import__("datetime").datetime.utcnow()

    def list_orders(self, account_id: UUID, symbol: str | None = None, limit: int = 100) -> list[PaperOrder]:
        orders = [o for o in self._orders.values() if o.account_id == account_id]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return sorted(orders, key=lambda o: o.created_at, reverse=True)[:limit]

    def upsert_position(self, position: PaperPosition) -> None:
        self._positions[(position.account_id, position.symbol)] = position

    def get_position(self, account_id: UUID, symbol: str) -> PaperPosition | None:
        return self._positions.get((account_id, symbol))

    def list_positions(self, account_id: UUID) -> list[PaperPosition]:
        return [p for p in self._positions.values() if p.account_id == account_id]

    def record_fill(self, fill: PaperFill) -> None:
        self._fills.append(fill)

    def list_fills(self, account_id: UUID, symbol: str | None = None, limit: int = 100) -> list[PaperFill]:
        # Derive fills from orders to get account_id
        order_ids = {o.order_id for o in self._orders.values() if o.account_id == account_id}
        fills = [f for f in self._fills if f.order_id in order_ids]
        if symbol:
            fills = [f for f in fills if f.symbol == symbol]
        return sorted(fills, key=lambda f: f.ts, reverse=True)[:limit]

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self._snapshots.append(snapshot)

    def get_latest_snapshot(self, account_id: UUID) -> PortfolioSnapshot | None:
        snapshots = [s for s in self._snapshots if s.account_id == account_id]
        return max(snapshots, key=lambda s: s.ts) if snapshots else None


class SqliteRepository(BaseRepository):
    """SQLite-backed repository for persistence."""

    def __init__(self, db_path: str = ".paper_trading.db") -> None:
        self.db_path = db_path
        self._init_tables()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS paper_accounts (
            account_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            balance TEXT,
            leverage TEXT,
            max_drawdown_pct TEXT,
            max_positions INTEGER,
            max_single_trade_pct TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS paper_orders (
            order_id TEXT PRIMARY KEY,
            account_id TEXT REFERENCES paper_accounts(account_id),
            idempotency_key TEXT UNIQUE,
            symbol TEXT NOT NULL,
            side TEXT,
            qty TEXT,
            entry_price TEXT,
            status TEXT,
            leverage TEXT,
            slippage_bps TEXT,
            fee_rate TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_orders_account ON paper_orders(account_id, symbol, status);
        CREATE TABLE IF NOT EXISTS paper_positions (
            account_id TEXT,
            symbol TEXT,
            side TEXT,
            qty TEXT,
            entry_price TEXT,
            margin TEXT,
            leverage TEXT,
            unrealized_pnl TEXT,
            realized_pnl TEXT,
            updated_at TEXT,
            PRIMARY KEY (account_id, symbol)
        );
        CREATE TABLE IF NOT EXISTS paper_fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT REFERENCES paper_orders(order_id),
            symbol TEXT,
            side TEXT,
            qty TEXT,
            price TEXT,
            fee TEXT,
            ts TEXT
        );
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            ts TEXT,
            account_id TEXT,
            cash_balance TEXT,
            total_equity TEXT,
            peak_equity TEXT,
            drawdown_pct TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_account ON portfolio_snapshots(account_id, ts DESC);
        """
        with self._conn() as conn:
            conn.executescript(ddl)
            try:
                conn.execute("ALTER TABLE paper_accounts ADD COLUMN initial_balance TEXT")
            except Exception:
                pass
            conn.commit()

    def _to_row(self, obj: Any) -> dict[str, Any]:
        """Serialize Pydantic model to DB-compatible dict."""
        data = obj.model_dump()
        for k, v in data.items():
            if isinstance(v, UUID):
                data[k] = str(v)
            elif isinstance(v, Decimal):
                data[k] = str(v)
            elif hasattr(v, "isoformat"):
                data[k] = v.isoformat()
        return data

    def create_account(self, account: PaperAccount) -> PaperAccount:
        if account.initial_balance is None:
            account.initial_balance = account.balance
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO paper_accounts
                (account_id, name, balance, initial_balance, leverage, max_drawdown_pct, max_positions, max_single_trade_pct, created_at)
                VALUES (:account_id, :name, :balance, :initial_balance, :leverage, :max_drawdown_pct, :max_positions, :max_single_trade_pct, :created_at)""",
                self._to_row(account),
            )
            conn.commit()
        return account

    def update_account(self, account: PaperAccount) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE paper_accounts
                SET balance = :balance, initial_balance = :initial_balance, leverage = :leverage
                WHERE account_id = :account_id""",
                self._to_row(account),
            )
            conn.commit()

    def get_account(self, account_id: UUID) -> PaperAccount | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM paper_accounts WHERE account_id = ?", (str(account_id),)
            ).fetchone()
        if not row:
            return None
        data = {k: row[k] for k in row.keys()}
        if data.get("initial_balance") in (None, ""):
            data["initial_balance"] = "10000"
        return PaperAccount(**data)

    def list_accounts(self) -> list[PaperAccount]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM paper_accounts").fetchall()
        out: list[PaperAccount] = []
        for r in rows:
            data = {k: r[k] for k in r.keys()}
            if data.get("initial_balance") in (None, ""):
                data["initial_balance"] = "10000"
            out.append(PaperAccount(**data))
        return out

    def create_order(self, order: PaperOrder) -> PaperOrder:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO paper_orders
                (order_id, account_id, idempotency_key, symbol, side, qty, entry_price, status, leverage, slippage_bps, fee_rate, created_at, updated_at)
                VALUES (:order_id, :account_id, :idempotency_key, :symbol, :side, :qty, :entry_price, :status, :leverage, :slippage_bps, :fee_rate, :created_at, :updated_at)""",
                self._to_row(order),
            )
            conn.commit()
        return order

    def get_order(self, order_id: UUID) -> PaperOrder | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM paper_orders WHERE order_id = ?", (str(order_id),)).fetchone()
        return PaperOrder(**{k: row[k] for k in row.keys()}) if row else None

    def get_order_by_idempotency(self, key: str) -> PaperOrder | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM paper_orders WHERE idempotency_key = ?", (key,)).fetchone()
        return PaperOrder(**{k: row[k] for k in row.keys()}) if row else None

    def update_order_status(self, order_id: UUID, status: OrderStatus) -> None:
        import datetime as _dt
        with self._conn() as conn:
            conn.execute(
                "UPDATE paper_orders SET status = ?, updated_at = ? WHERE order_id = ?",
                (status.value, _dt.datetime.utcnow().isoformat(), str(order_id)),
            )
            conn.commit()

    def list_orders(self, account_id: UUID, symbol: str | None = None, limit: int = 100) -> list[PaperOrder]:
        sql = "SELECT * FROM paper_orders WHERE account_id = ?"
        params: list[Any] = [str(account_id)]
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [PaperOrder(**{k: r[k] for k in r.keys()}) for r in rows]

    def upsert_position(self, position: PaperPosition) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO paper_positions
                (account_id, symbol, side, qty, entry_price, margin, leverage, unrealized_pnl, realized_pnl, updated_at)
                VALUES (:account_id, :symbol, :side, :qty, :entry_price, :margin, :leverage, :unrealized_pnl, :realized_pnl, :updated_at)
                ON CONFLICT(account_id, symbol) DO UPDATE SET
                side=excluded.side, qty=excluded.qty, entry_price=excluded.entry_price,
                margin=excluded.margin, leverage=excluded.leverage,
                unrealized_pnl=excluded.unrealized_pnl, realized_pnl=excluded.realized_pnl, updated_at=excluded.updated_at""",
                self._to_row(position),
            )
            conn.commit()

    def get_position(self, account_id: UUID, symbol: str) -> PaperPosition | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM paper_positions WHERE account_id = ? AND symbol = ?",
                (str(account_id), symbol),
            ).fetchone()
        return PaperPosition(**{k: row[k] for k in row.keys()}) if row else None

    def list_positions(self, account_id: UUID) -> list[PaperPosition]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM paper_positions WHERE account_id = ?", (str(account_id),)
            ).fetchall()
        return [PaperPosition(**{k: r[k] for k in r.keys()}) for r in rows]

    def record_fill(self, fill: PaperFill) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO paper_fills (fill_id, order_id, symbol, side, qty, price, fee, ts) VALUES (:fill_id, :order_id, :symbol, :side, :qty, :price, :fee, :ts)",
                self._to_row(fill),
            )
            conn.commit()

    def list_fills(self, account_id: UUID, symbol: str | None = None, limit: int = 100) -> list[PaperFill]:
        with self._conn() as conn:
            sql = """SELECT f.* FROM paper_fills f
                     JOIN paper_orders o ON f.order_id = o.order_id
                     WHERE o.account_id = ?"""
            params: list[Any] = [str(account_id)]
            if symbol:
                sql += " AND f.symbol = ?"
                params.append(symbol)
            sql += " ORDER BY f.ts DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        return [PaperFill(**{k: r[k] for k in r.keys()}) for r in rows]

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO portfolio_snapshots (ts, account_id, cash_balance, total_equity, peak_equity, drawdown_pct) VALUES (:ts, :account_id, :cash_balance, :total_equity, :peak_equity, :drawdown_pct)",
                self._to_row(snapshot),
            )
            conn.commit()

    def get_latest_snapshot(self, account_id: UUID) -> PortfolioSnapshot | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM portfolio_snapshots WHERE account_id = ? ORDER BY ts DESC LIMIT 1",
                (str(account_id),),
            ).fetchone()
        return PortfolioSnapshot(**{k: row[k] for k in row.keys()}) if row else None
