# OrderBookCollector design

## Goal
Provide a minimal `OrderBookCollector` implementation for `collector-service` that can be instantiated by the runtime, exposes `run()`, `stop()`, and `close()`, and keeps a lightweight data path into `raw.crypto_order_book_tick`. The collector must avoid copying the preview service wholesale and stay compatible with Python 3.6 and the existing Timescale/ccxt stack.

## Chosen approach
1. Poll the REST order book via the existing `ccxt` exchange client at `crypto_orderbook.tick_interval` (default 1 second).
2. For each symbol we compute top-of-book statistics (mid price, spread, bid/ask 1, depth within 1%, imbalance) and persist rows into `raw.crypto_order_book_tick`.
3. `run()` loops until a threading `Event` is set, `stop()` raises the event, and `close()` is an alias for `stop()`. This mirrors `WSCollector`'s lifecycle without introducing async buffering.

## Configuration
* Use `load_config().crypto_orderbook` to pluck `enabled`, `tick_interval`, `depth`, `symbols`, etc.
* Default to Binance (`ccxt.binance`) for symbol polling if no explicit symbol list is provided.
* Deduplicate and normalize symbols via `common.symbols.get_configured_symbols` when available.
* Respect `crypto_orderbook.depth` when calling `fetch_order_book`.

## Runtime components
- **Symbol preparation**: build a list of exchange symbol identifiers (e.g., `BTC/USDT`) based on config or `common.symbols`; store normalized IDs for both polling and the Timescale `symbol` column.
- **CCXT client**: instantiate once during initialization to reuse rate-limit handling.
- **Polling loop**: `run()` repeatedly calls `_poll_once()`, which walks the symbol list, fetches the order book, constructs tick rows, and issues a batched insert. After each cycle, wait `tick_interval` seconds (accounting for the fetch duration) unless `stop()` was called.
- **Row construction**: derive `mid_price`, `spread_bps`, `bid_depth_1pct`, `ask_depth_1pct`, and `imbalance` from the top few tiers; wrap numeric values as `Decimal` for Timescale insertion. Add `exchange="binance"` and `source="collector-service-orderbook"` to maintain lineage.
- **Persistence**: use `TimescaleAdapter.connection()` to run a `COPY` or `INSERT ... ON CONFLICT DO NOTHING` to `raw.crypto_order_book_tick`. Only insert tick-level rows; the L2 `raw.crypto_order_book` table is out of scope for this minimum viable implementation.
- **Metrics**: emit counters such as `order_book_tick_written`, `order_book_tick_errors`, and `order_book_poll_cycles`.

## Error handling
- Wrap each call to `fetch_order_book` in a try/except to prevent a single symbol failure from stopping the entire run; log once per symbol per cycle and increment an error metric.
- If CCXT or `datetime` conversions fail during init, raise immediately so the runtime can detect and stop.
- Use `stop()` to break out of sleeping waits and let `run()` exit cleanly; the runtime may call `close()` after `run()` returns.

## Testing / verification
- Unit-test the tick-row builder separately using canned order books to ensure spread/depth/imbalance math behaves.
- Integration smoke test could instantiate the collector with `tick_interval=0.1`, run for a few loops against a fake `ccxt` client (monkeypatching) and ensure `raw.crypto_order_book_tick` receives rows via a dummy `TimescaleAdapter`.
- Verify the config path continues to parse environment overrides by reusing the existing `test_config` coverage.

## Risks and unknowns
- Without a config key for exchange/provider, the collector assumes Binance; supporting other exchanges will need new config entries or symbol mapping logic later.
- The implementation only writes to the L1 tick table and skips the full-depth table, so any downstream that expects `raw.crypto_order_book` must be adapted later.
- Polling via REST is less real-time than a websocket stream and is subject to API rate limits; configure `crypto_orderbook.tick_interval` and `runtime.rate_limit_per_minute` accordingly.

## Next steps
1. Wait for this spec to be reviewed. Once approved, invoke the writing-plans skill to create the step-by-step implementation plan.
2. Implement `OrderBookCollector` and update `src/collectors/crypto/__init__.py` to expose it.
3. Run targeted tests (e.g., new unit tests for row generation) and document any limitations discovered during implementation.
