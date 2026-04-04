# OrderBookCollector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a minimal poll-based `OrderBookCollector` that computes L1 stats from CCXT order books and writes them into `raw.crypto_order_book_tick`, exposing `run()`, `stop()`, and `close()` for the runtime.

**Architecture:** A simple polling loop fetches REST order books via CCXT at `prcfg.crypto_orderbook.tick_interval`, builds metric rows, and batches them into Timescale via a raw `INSERT ... ON CONFLICT DO NOTHING`. Lifecycle management relies on a `threading.Event` so `run()` blocks until `stop()`/`close()` signal completion.

**Tech Stack:** Python 3.6 (no async), `ccxt`, `psycopg_pool` via `TimescaleAdapter.connection()`, `threading`, `decimal.Decimal`, `common.symbols` for defaults.

---

### Task 1: Protect tick-row math with tests

**Files:**
- Create: `services/collector-service/tests/test_order_book_collector.py`
- Modify: `services/collector-service/src/collectors/crypto/order_book.py`
- Test: `services/collector-service/tests/test_order_book_collector.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_tick_row_computes_spread():
    collector = OrderBookCollector(symbols=["BTCUSDT"])
    row = collector._build_tick_row(
        symbol="BTCUSDT",
        timestamp=datetime.utcnow(),
        bids=[(50000.0, 1.5), (49950.0, 2.0)],
        asks=[(50010.0, 1.0), (50020.0, 0.5)],
    )
    assert row["spread_bps"] == Decimal("4.0000")
    assert row["bid1_price"] == Decimal("50000")
    assert row["ask1_price"] == Decimal("50010")
    assert row["imbalance"] == Decimal("0.1667")
```

- [ ] **Step 2: Run it so it fails**
Run: `python -m pytest services/collector-service/tests/test_order_book_collector.py::test_build_tick_row_computes_spread -q`
Expected: FAIL because `_build_tick_row` is not implemented yet.

- [ ] **Step 3: Implement the helper**

```python
class OrderBookCollector(object):
    def _build_tick_row(self, symbol, timestamp, bids, asks):
        if not bids or not asks:
            return None
        bid1_price, bid1_size = bids[0]
        ask1_price, ask1_size = asks[0]
        mid = (bid1_price + ask1_price) / 2
        spread = ask1_price - bid1_price
        spread_bps = Decimal(spread) / Decimal(mid) * Decimal("10000") if mid else Decimal("0")
        bid_depth = self._sum_depth(bids, mid, Decimal("0.01"))
        ask_depth = self._sum_depth(asks, mid, Decimal("0.01"))
        imbalance = (
            (Decimal(bid_depth) - Decimal(ask_depth)) / Decimal(bid_depth + ask_depth)
            if (bid_depth + ask_depth) > 0
            else Decimal("0")
        )
        return {
            "symbol": symbol,
            "timestamp": timestamp,
            "exchange": "binance",
            "mid_price": Decimal(str(mid)),
            "spread_bps": spread_bps.quantize(Decimal("0.0001")),
            "bid1_price": Decimal(str(bid1_price)),
            "bid1_size": Decimal(str(bid1_size)),
            "ask1_price": Decimal(str(ask1_price)),
            "ask1_size": Decimal(str(ask1_size)),
            "bid_depth_1pct": Decimal(str(bid_depth)),
            "ask_depth_1pct": Decimal(str(ask_depth)),
            "imbalance": imbalance.quantize(Decimal("0.0001")),
            "source": "collector-service-orderbook",
        }
```

- [ ] **Step 4: Run the test to make sure it passes**
Run: `python -m pytest services/collector-service/tests/test_order_book_collector.py::test_build_tick_row_computes_spread -q`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add services/collector-service/src/collectors/crypto/order_book.py services/collector-service/tests/test_order_book_collector.py
git commit -m "feat(orderbook): add L1 tick row builder"
```

### Task 2: Add polling loop and persistence

**Files:**
- Modify: `services/collector-service/src/collectors/crypto/order_book.py`
- Test: `services/collector-service/tests/test_order_book_collector.py`

- [ ] **Step 1: Write failing test for `_write_tick_rows` being called with batched rows**

```python
def test_poll_once_writes_rows(monkeypatch):
    written = []
    class DummyTimescale:
        def __init__(self):
            self.rows = []
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def cursor(self):
            return self
        def execute(self, query, params=None):
            written.append(params)

    collector = OrderBookCollector(symbols=["BTC/USDT"])
    monkeypatch.setattr(collector, "_fetch_order_book", lambda s: {"bids": [(1, 1)], "asks": [(2, 1)]})
    monkeypatch.setattr(collector, "_get_connection", lambda: DummyTimescale())
    collector._poll_once()
    assert written, "Rows should be written to Timescale"
```

- [ ] **Step 2: Run test**
Run: `python -m pytest services/collector-service/tests/test_order_book_collector.py::test_poll_once_writes_rows -q`
Expected: FAIL because `_write_tick_rows` and `_poll_once` do not exist yet.

- [ ] **Step 3: Implement `_fetch_order_book`, `_poll_once`, `_write_tick_rows`, and `_get_connection`**

```python
    def _get_connection(self):
        ts = self._ts
        return ts.connection()

    def _fetch_order_book(self, symbol):
        exchange = self._ccxt_client or self._init_ccxt()
        return exchange.fetch_order_book(symbol, limit=self._config.crypto_orderbook.depth)

    def _poll_once(self):
        rows = []
        now = datetime.utcnow()
        for symbol in self._symbols:
            try:
                book = self._fetch_order_book(symbol)
            except Exception as exc:
                self._metrics.inc("order_book_tick_errors")
                logger.warning("order book fetch failed: %s", exc)
                continue
            row = self._build_tick_row(symbol, now, book.get("bids", []), book.get("asks", []))
            if row:
                rows.append(row)
        self._write_tick_rows(rows)

    def _write_tick_rows(self, rows):
        if not rows:
            return
        sql = (
            "INSERT INTO raw.crypto_order_book_tick (exchange, symbol, timestamp, mid_price, spread_bps,"
            " bid1_price, bid1_size, ask1_price, ask1_size, bid_depth_1pct, ask_depth_1pct, imbalance, source)"
            " VALUES (%(exchange)s, %(symbol)s, %(timestamp)s, %(mid_price)s, %(spread_bps)s,"
            " %(bid1_price)s, %(bid1_size)s, %(ask1_price)s, %(ask1_size)s, %(bid_depth_1pct)s,"
            " %(ask_depth_1pct)s, %(imbalance)s, %(source)s)"
            " ON CONFLICT (exchange, symbol, timestamp) DO UPDATE SET updated_at = now()"
        )
        with self._ts.connection() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(sql, row)
            conn.commit()
        self._metrics.inc("order_book_tick_written", len(rows))
```

- [ ] **Step 4: Run the poll test and any other dependent tests**
Run: `python -m pytest services/collector-service/tests/test_order_book_collector.py -q`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add services/collector-service/src/collectors/crypto/order_book.py services/collector-service/tests/test_order_book_collector.py
git commit -m "feat(orderbook): add polling persistence"
```

### Task 3: Lifecycle, configuration, and symbol loading

**Files:**
- Modify: `services/collector-service/src/collectors/crypto/order_book.py`
- Test: `services/collector-service/tests/test_order_book_collector.py`

- [ ] **Step 1: Write failing test verifying `_load_symbols` handles config overrides**

```python
def test_load_symbols_uses_config(get_configured_symbols):
    collector = OrderBookCollector(config=ConfigHolder(symbols=["BTCUSDT"], crypto_orderbook=ConfigSection()))
    assert collector._symbols == ["BTCUSDT"]
```
```

- [ ] **Step 2: Run test**
Run: `python -m pytest services/collector-service/tests/test_order_book_collector.py::test_load_symbols_uses_config -q`
Expected: FAIL because `_load_symbols` is incomplete.

- [ ] **Step 3: Implement lifecycle weapons**

```python
    def __init__(self, config=None, timescale=None, metrics_client=None):
        self._config = config or load_config()
        self._ts = timescale or TimescaleAdapter()
        self._metrics = metrics_client or metrics
        self._tick_interval = float(self._config.crypto_orderbook.tick_interval or 1)
        self._symbols = self._load_symbols()
        self._stop_event = threading.Event()
        self._ccxt_client = None

    def _load_symbols(self):
        requested = getattr(self._config.crypto_orderbook, "symbols", []) or []
        if requested:
            return [normalize_symbol(s) for s in requested if normalize_symbol(s)]
        try:
            return [normalize_symbol(s) for s in get_configured_symbols() if normalize_symbol(s)]
        except Exception:
            return []

    def run(self):
        self._stop_event.clear()
        while not self._stop_event.is_set():
            start = time.time()
            self._poll_once()
            elapsed = time.time() - start
            wait = max(0.0, self._tick_interval - elapsed)
            if self._stop_event.wait(wait):
                break

    def stop(self):
        self._stop_event.set()

    def close(self):
        self.stop()
        if self._ccxt_client is not None:
            self._ccxt_client.close()
```

- [ ] **Step 4: Run the lifecycle tests plus the earlier suite**
Run: `python -m pytest services/collector-service/tests/test_order_book_collector.py -q`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add services/collector-service/src/collectors/crypto/order_book.py
git commit -m "feat(orderbook): add lifecycle management"
```

### Task 4: Public API and documentation updates

**Files:**
- Modify: `services/collector-service/src/collectors/crypto/__init__.py`
- Modify: `docs/superpowers/specs/2026-03-31-orderbook-collector-design.md`

- [ ] **Step 1: Write failing test that ensures `OrderBookCollector` is exported**

```python
def test_orderbook_collector_exported():
    from src.collectors.crypto import __all__ as exports
    assert "OrderBookCollector" in exports
```

- [ ] **Step 2: Run brief check**
Run: `python -m py_compile services/collector-service/src/collectors/crypto/__init__.py`
Expected: PASS

- [ ] **Step 3: Export the collector and reference the design file**

```python
from .order_book import OrderBookCollector

__all__ = ["DataBackfiller", "GapFiller", "GapScanner", "MetricsCollector", "OrderBookCollector", "WSCollector"]
```

- [ ] **Step 4: Re-run the earlier pytest suite**
Run: `python -m pytest services/collector-service/tests/test_order_book_collector.py -q`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add services/collector-service/src/collectors/crypto/__init__.py docs/superpowers/specs/2026-03-31-orderbook-collector-design.md
git commit -m "feat(orderbook): publish collector and document design"
```
