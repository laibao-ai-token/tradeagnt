"""Auto-consumer: polls signal_history.db and feeds signals into paper trading."""

import sqlite3
import threading
import time
from decimal import Decimal


def start_auto_consumer(signal_db: str, paper_db: str, refresh_s: float = 5.0) -> threading.Thread:
    from tradecat.core.paper_trading.engine import PaperTradingEngine
    from tradecat.core.paper_trading.repository import SqliteRepository

    engine = PaperTradingEngine(SqliteRepository(paper_db))
    accounts = engine.list_accounts()
    if not accounts:
        engine.create_account("default", balance=Decimal("10000"), leverage=Decimal("1"))
        accounts = engine.list_accounts()
    account_id = accounts[0].account_id
    last_id = 0

    def _run():
        nonlocal last_id
        while True:
            time.sleep(refresh_s)
            try:
                conn = sqlite3.connect(signal_db)
                cur = conn.execute(
                    "SELECT id, symbol, direction, strength, price FROM signal_history "
                    "WHERE id > ? ORDER BY id LIMIT 50",
                    (last_id,),
                )
                rows = cur.fetchall()
                conn.close()
                for row in rows:
                    id_, symbol, direction, strength, price = row
                    last_id = id_
                    side = (
                        "LONG"
                        if direction in ("LONG", "BUY")
                        else "SHORT"
                        if direction in ("SHORT", "SELL")
                        else "NEUTRAL"
                    )
                    if side == "NEUTRAL":
                        continue
                    price_dec = Decimal(str(price)) if price else Decimal("1")
                    payload = {
                        "symbol": symbol,
                        "side": side,
                        "idempotency_key": f"autoconsumer_sig_{id_}",
                    }
                    engine.from_signal(account_id, payload, price_dec)
            except Exception:
                pass

    t = threading.Thread(target=_run, name="auto-consumer", daemon=True)
    t.start()
    return t
