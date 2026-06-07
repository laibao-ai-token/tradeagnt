"""Auto-consumer: polls signal_history.db and feeds signals into paper trading."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from decimal import Decimal
from pathlib import Path

from tradecat.core.paper_trading.models import Side
from tradecat.core.symbols import infer_market_from_symbol, is_close_only_sell, normalize_market, normalize_symbol

logger = logging.getLogger(__name__)


def agent_mode_enabled() -> bool:
    """When set, TUI must not auto-trade paper; Agent harness owns writes (P6 / E1)."""
    return (os.getenv("TRADEAGNT_AGENT_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


def _resolve_consumer_markets() -> set[str]:
    """Markets auto-consumer may trade. ``all`` / ``*`` → crypto + us_stock."""
    explicit = (os.getenv("PAPER_AUTO_MARKET") or os.getenv("TUI_SIGNAL_MARKET") or "").strip()
    if explicit:
        raw = explicit.lower()
        if raw in {"all", "*", "both", "dual"}:
            return {"crypto", "us_stock"}
        return {normalize_market(explicit)}

    strategy_path = (os.getenv("TUI_SIGNAL_STRATEGY") or "current/fast_1m.yaml").strip()
    markets: set[str] = set()
    try:
        from tradecat.core.signals import StrategyLoader

        markets.add(normalize_market(StrategyLoader.load(strategy_path).market))
    except Exception:
        markets.add("crypto")

    extra = (os.getenv("TUI_SIGNAL_STRATEGY_EXTRA") or "").strip()
    if extra:
        try:
            from tradecat.core.signals import StrategyLoader

            markets.add(normalize_market(StrategyLoader.load(extra).market))
        except Exception:
            pass
    if len(markets) > 1:
        return markets
    return markets or {"crypto"}


def _market_for_signal(symbol: str, allowed: set[str]) -> str | None:
    """Pick execution market for a signal row; None if not in allowed set."""
    inferred = infer_market_from_symbol(symbol)
    if inferred in allowed:
        return inferred
    for m in allowed:
        norm = normalize_symbol(symbol, m)
        if norm and infer_market_from_symbol(norm) == m:
            return m
    return None


def _direction_to_side(direction: str, market: str) -> Side | None:
    d = (direction or "").strip().upper()
    if is_close_only_sell(market):
        if d in ("LONG", "BUY"):
            return Side.LONG
        if d in ("SELL", "SHORT"):
            return Side.LONG  # handled as close in _execute_signal
        return None
    if d in ("LONG", "BUY"):
        return Side.LONG
    if d in ("SHORT", "SELL"):
        return Side.SHORT
    return None


def _auto_notional_pct() -> Decimal:
    raw = os.getenv("PAPER_AUTO_NOTIONAL_PCT", "0.15").strip() or "0.15"
    try:
        pct = Decimal(raw)
    except Exception:
        pct = Decimal("0.15")
    return max(Decimal("0.01"), min(pct, Decimal("0.50")))


def _min_signal_strength() -> int:
    try:
        return int(os.getenv("PAPER_AUTO_MIN_STRENGTH", "50").strip() or "50")
    except Exception:
        return 50


def _trade_cooldown_s() -> float:
    """Min seconds between two paper trades on the same symbol."""
    try:
        return max(60.0, float(os.getenv("PAPER_AUTO_TRADE_COOLDOWN_S", "180").strip() or "180"))
    except Exception:
        return 180.0


def _min_equity_ratio() -> Decimal:
    """Stop opening new risk when NAV / initial < ratio (0 = disabled)."""
    raw = os.getenv("PAPER_AUTO_MIN_EQUITY_RATIO", "0.20").strip() or "0.20"
    try:
        r = Decimal(raw)
    except Exception:
        r = Decimal("0.20")
    return max(Decimal("0"), min(r, Decimal("1")))


def _trade_notional(acct, pct: Decimal) -> Decimal:
    """Order size: cash when positive; else fraction of initial capital."""
    initial = getattr(acct, "initial_balance", None) or Decimal("10000")
    if initial <= 0:
        initial = Decimal("10000")
    if acct.balance > 0:
        return acct.balance * pct
    return initial * pct


def _consumer_state_path(paper_db: str) -> Path:
    return Path(paper_db).with_suffix(".consumer_state.json")


def _load_last_id(paper_db: str) -> int:
    path = _consumer_state_path(paper_db)
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("last_signal_id", 0))
    except Exception:
        return 0


def _save_last_id(paper_db: str, last_id: int) -> None:
    path = _consumer_state_path(paper_db)
    try:
        path.write_text(
            json.dumps({"last_signal_id": last_id, "updated_at": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _execute_signal(
    engine,
    account_id,
    *,
    sym: str,
    direction: str,
    market: str,
    price: Decimal,
    notional: Decimal,
    signal_id: int,
    positions: list,
) -> dict:
    """Apply one signal row to paper engine (market-aware)."""
    d = (direction or "").strip().upper()
    m = normalize_market(market)
    idem = f"autoconsumer_sig_{signal_id}"

    if is_close_only_sell(m) and d in ("SELL", "SHORT"):
        pos = next(
            (p for p in positions if p.symbol == sym and p.qty > 0 and p.side == Side.LONG),
            None,
        )
        if not pos:
            return {"ok": False, "error": "no_long_to_close", "skipped": True}
        return engine.close(account_id, sym, price)

    side = _direction_to_side(d, m)
    if side is None:
        return {"ok": False, "error": "invalid direction", "skipped": True}

    pos = next((p for p in positions if p.symbol == sym and p.qty > 0), None)
    if pos and pos.side == side:
        return {"ok": False, "error": "same_side_skip", "skipped": True}

    if pos and pos.side != side:
        close_res = engine.close(account_id, sym, price)
        if not close_res.get("ok"):
            return close_res
        return engine._open_order(account_id, sym, side, notional, price, Decimal("1"))

    payload = {
        "symbol": sym,
        "market": m,
        "side": side.value,
        "qty_notional": str(notional),
        "idempotency_key": idem,
    }
    return engine.from_signal(account_id, payload, price)


def start_auto_consumer(signal_db: str, paper_db: str, refresh_s: float = 5.0) -> threading.Thread | None:
    if agent_mode_enabled():
        logger.info("TRADEAGNT_AGENT_MODE enabled: auto_consumer not started (paper writes via Agent only)")
        return None

    from tradecat.core.paper_trading.engine import PaperTradingEngine
    from tradecat.core.paper_trading.repository import SqliteRepository

    engine = PaperTradingEngine(SqliteRepository(paper_db))
    accounts = engine.list_accounts()
    if not accounts:
        engine.create_account("default", balance=Decimal("10000"), leverage=Decimal("1"))
        accounts = engine.list_accounts()
    account_id = accounts[0].account_id
    last_id = _load_last_id(paper_db)
    notional_pct = _auto_notional_pct()
    min_strength = _min_signal_strength()
    trade_cd = _trade_cooldown_s()
    min_equity_ratio = _min_equity_ratio()
    last_trade_at: dict[str, float] = {}
    consumer_markets = _resolve_consumer_markets()

    def _equity_ok() -> bool:
        if min_equity_ratio <= 0:
            return True
        st = engine.status(account_id)
        initial = st.get("initial_capital") or Decimal("10000")
        nav = st.get("nav") or Decimal("0")
        if initial <= 0:
            return True
        return nav >= initial * min_equity_ratio

    def _run() -> None:
        nonlocal last_id
        poll_s = max(3.0, float(refresh_s))
        while True:
            time.sleep(poll_s)
            try:
                if not _equity_ok():
                    continue

                conn = sqlite3.connect(signal_db)
                cur = conn.execute(
                    "SELECT id, symbol, direction, strength, price FROM signal_history "
                    "WHERE id > ? ORDER BY id LIMIT 50",
                    (last_id,),
                )
                rows = cur.fetchall()
                conn.close()

                if not rows:
                    continue

                positions = engine.status(account_id).get("positions", [])
                now = time.time()

                for row in rows:
                    id_, symbol, direction, strength, price = row
                    last_id = max(last_id, int(id_))

                    if int(strength or 0) < min_strength:
                        continue

                    trade_market = _market_for_signal(str(symbol or ""), consumer_markets)
                    if not trade_market:
                        continue
                    sym = normalize_symbol(symbol, trade_market)
                    if not sym:
                        continue
                    if not price or float(price) <= 0:
                        continue

                    last_ts = last_trade_at.get(sym, 0.0)
                    if (now - last_ts) < trade_cd:
                        continue

                    acct = engine.get_account(account_id)
                    if not acct:
                        continue
                    notional = _trade_notional(acct, notional_pct)
                    if notional <= 0:
                        continue

                    result = _execute_signal(
                        engine,
                        account_id,
                        sym=sym,
                        direction=str(direction or ""),
                        market=trade_market,
                        price=Decimal(str(price)),
                        notional=notional,
                        signal_id=int(id_),
                        positions=positions,
                    )

                    if result.get("ok"):
                        last_trade_at[sym] = now
                        positions = engine.status(account_id).get("positions", [])
                    elif not result.get("skipped"):
                        err = result.get("error", "unknown")
                        if "idempotency" not in str(err):
                            logger.info(
                                "auto_consumer signal %s %s %s: %s",
                                id_,
                                sym,
                                direction,
                                err,
                            )

                _save_last_id(paper_db, last_id)
            except Exception as exc:
                logger.debug("auto_consumer loop error: %s", exc)

    t = threading.Thread(target=_run, name="auto-consumer", daemon=True)
    t.start()
    return t
