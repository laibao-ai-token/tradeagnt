"""Crypto order book collector for collector-service runtime."""

from __future__ import absolute_import

import json
import logging
import threading
import time
from datetime import datetime
from decimal import Decimal

from src.adapters.cryptofeed import apply_feed_proxies, attach_ws_proxy, build_feedhandler_config, preload_symbols
from src.adapters.metrics import metrics
from src.adapters.timescale import TimescaleAdapter
from src.config import load_config

from .ws import load_symbols, normalize_symbol


logger = logging.getLogger(__name__)


class OrderBookCollector(object):
    """Minimal Binance futures order book collector with dual-layer sampling."""

    FLUSH_WINDOW = 1.0
    MAX_TICK_BUFFER = 5000
    MAX_FULL_BUFFER = 1000

    def __init__(self, config=None, timescale=None, metrics_client=None):
        self._config = config or load_config()
        self._ts = timescale or TimescaleAdapter()
        self._metrics = metrics_client or metrics
        self._symbols = self._load_symbols()
        self._stop_event = threading.Event()
        self._buffer_lock = threading.Lock()
        self._flush_timer = None
        self._handler = None
        self._tick_buffer = []
        self._full_buffer = []
        self._last_tick = {}
        self._last_full = {}
        self._last_seq = {}

    def _configured_symbols(self):
        orderbook_symbols = list(getattr(self._config.crypto_orderbook, "symbols", []) or [])
        if orderbook_symbols:
            return orderbook_symbols
        return list(getattr(self._config.crypto_kline, "symbols", []) or [])

    def _load_symbols(self):
        raw_symbols = self._configured_symbols() or load_symbols(
            getattr(self._config.crypto_kline, "ccxt_exchange", "binance")
        )
        mapping = {}
        for symbol in raw_symbols:
            normalized = normalize_symbol(symbol)
            if not normalized:
                continue
            mapping["{0}-USDT-PERP".format(normalized[:-4])] = normalized
        if not mapping:
            raise RuntimeError("no symbols available for crypto order book collector")
        preload_symbols(list(mapping.values()))
        logger.info("loaded order book symbols=%d", len(mapping))
        return mapping

    def _tick_interval_seconds(self):
        return max(1.0, float(getattr(self._config.crypto_orderbook, "tick_interval", 1)))

    def _full_interval_seconds(self):
        return max(1.0, float(getattr(self._config.crypto_orderbook, "full_interval", 5)))

    def _source_name(self):
        return getattr(self._config.crypto_kline, "ws_source", "binance_ws")

    def _exchange_name(self):
        return getattr(self._config.crypto_kline, "db_exchange", "binance_futures_um")

    def _depth_limit(self):
        return max(1, int(getattr(self._config.crypto_orderbook, "depth", 1000)))

    def _drain_buffers_locked(self):
        tick_rows = list(self._tick_buffer)
        full_rows = list(self._full_buffer)
        self._tick_buffer = []
        self._full_buffer = []
        self._flush_timer = None
        return tick_rows, full_rows

    def _schedule_flush_locked(self):
        if self.FLUSH_WINDOW <= 0 or self._flush_timer is not None or self._stop_event.is_set():
            return
        timer = threading.Timer(self.FLUSH_WINDOW, self._flush_buffer)
        timer.daemon = True
        self._flush_timer = timer
        timer.start()

    def _flush_buffer(self):
        with self._buffer_lock:
            tick_rows, full_rows = self._drain_buffers_locked()
        return self._write_buffers(tick_rows, full_rows)

    def _final_flush(self):
        with self._buffer_lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
            tick_rows, full_rows = self._drain_buffers_locked()
        return self._write_buffers(tick_rows, full_rows)

    def _write_buffers(self, tick_rows, full_rows):
        written = {"tick": 0, "full": 0}
        if tick_rows:
            written["tick"] = self._write_tick_rows(tick_rows)
            self._metrics.inc("orderbook_tick_rows_written", written["tick"])
        if full_rows:
            written["full"] = self._write_full_rows(full_rows)
            self._metrics.inc("orderbook_full_rows_written", written["full"])
        return written

    def _write_tick_rows(self, rows):
        return self._write_rows("crypto_order_book_tick", rows)

    def _write_full_rows(self, rows):
        return self._write_rows("crypto_order_book", rows)

    def _write_rows(self, table_name, rows):
        if not rows:
            return 0

        columns = list(rows[0].keys())
        schema_name = getattr(self._config.database, "raw_db_schema", "raw")
        temp_table = self._ts._temp_table_name(table_name)
        conflict_keys = ("exchange", "symbol", "timestamp")

        with self._ts.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(self._ts._create_temp_table_query(temp_table, schema_name, table_name))
                with cur.copy(self._ts._copy_query(temp_table, columns)) as copy:
                    for row in rows:
                        copy.write_row(tuple(row.get(column) for column in columns))
                cur.execute(
                    self._ts._upsert_query(
                        schema_name,
                        table_name,
                        temp_table,
                        columns,
                        conflict_keys,
                        touch_updated_at=True,
                    )
                )
                written = cur.rowcount
            conn.commit()

        if written and written > 0:
            return written
        return len(rows)

    def _coerce_decimal(self, value):
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value))

    def _compute_depth_stats(self, mid_price, bids, asks):
        stats = {
            "bid_depth_1pct": Decimal("0"),
            "ask_depth_1pct": Decimal("0"),
            "bid_depth_5pct": Decimal("0"),
            "ask_depth_5pct": Decimal("0"),
            "bid_notional_1pct": Decimal("0"),
            "ask_notional_1pct": Decimal("0"),
            "bid_notional_5pct": Decimal("0"),
            "ask_notional_5pct": Decimal("0"),
        }
        if mid_price <= 0:
            return stats

        threshold_1pct = mid_price * 0.01
        threshold_5pct = mid_price * 0.05

        for price, size in bids:
            diff = mid_price - price
            price_value = Decimal(str(price))
            size_value = Decimal(str(size))
            notional = price_value * size_value
            if diff <= threshold_1pct:
                stats["bid_depth_1pct"] += size_value
                stats["bid_notional_1pct"] += notional
            if diff <= threshold_5pct:
                stats["bid_depth_5pct"] += size_value
                stats["bid_notional_5pct"] += notional
            else:
                break

        for price, size in asks:
            diff = price - mid_price
            price_value = Decimal(str(price))
            size_value = Decimal(str(size))
            notional = price_value * size_value
            if diff <= threshold_1pct:
                stats["ask_depth_1pct"] += size_value
                stats["ask_notional_1pct"] += notional
            if diff <= threshold_5pct:
                stats["ask_depth_5pct"] += size_value
                stats["ask_notional_5pct"] += notional
            else:
                break

        return stats

    def _build_tick_row(self, symbol, timestamp, bids_dict, asks_dict):
        if not bids_dict or not asks_dict:
            return None

        bid_prices = sorted(bids_dict.keys(), key=float, reverse=True)
        ask_prices = sorted(asks_dict.keys(), key=float)
        if not bid_prices or not ask_prices:
            return None

        bid1_price = float(bid_prices[0])
        ask1_price = float(ask_prices[0])
        bid1_size = float(bids_dict[bid_prices[0]])
        ask1_size = float(asks_dict[ask_prices[0]])
        mid_price = (bid1_price + ask1_price) / 2.0
        spread = ask1_price - bid1_price
        spread_bps = (spread / mid_price * 10000.0) if mid_price > 0 else 0.0

        bid_depth = 0.0
        for price in bid_prices[:50]:
            if mid_price - float(price) > mid_price * 0.01:
                break
            bid_depth += float(bids_dict[price])

        ask_depth = 0.0
        for price in ask_prices[:50]:
            if float(price) - mid_price > mid_price * 0.01:
                break
            ask_depth += float(asks_dict[price])

        total_depth = bid_depth + ask_depth
        imbalance = ((bid_depth - ask_depth) / total_depth) if total_depth > 0 else 0.0

        return {
            "exchange": self._exchange_name(),
            "symbol": symbol,
            "timestamp": timestamp,
            "mid_price": Decimal(str(mid_price)),
            "spread_bps": Decimal(str(round(spread_bps, 4))),
            "bid1_price": Decimal(str(bid1_price)),
            "bid1_size": Decimal(str(bid1_size)),
            "ask1_price": Decimal(str(ask1_price)),
            "ask1_size": Decimal(str(ask1_size)),
            "bid_depth_1pct": Decimal(str(bid_depth)),
            "ask_depth_1pct": Decimal(str(ask_depth)),
            "imbalance": Decimal(str(round(imbalance, 6))),
            "source": self._source_name(),
            "source_event_time": timestamp,
        }

    def _build_full_row(self, symbol, timestamp, bids_dict, asks_dict, last_update_id=None):
        if not bids_dict or not asks_dict:
            return None

        depth = self._depth_limit()
        bid_prices = sorted(bids_dict.keys(), key=float, reverse=True)[:depth]
        ask_prices = sorted(asks_dict.keys(), key=float)[:depth]
        if not bid_prices or not ask_prices:
            return None

        bid1_price = float(bid_prices[0])
        ask1_price = float(ask_prices[0])
        bid1_size = float(bids_dict[bid_prices[0]])
        ask1_size = float(asks_dict[ask_prices[0]])
        mid_price = (bid1_price + ask1_price) / 2.0
        spread = ask1_price - bid1_price
        spread_bps = (spread / mid_price * 10000.0) if mid_price > 0 else 0.0

        bids = [(float(price), float(bids_dict[price])) for price in bid_prices]
        asks = [(float(price), float(asks_dict[price])) for price in ask_prices]
        stats = self._compute_depth_stats(mid_price, bids, asks)
        total_depth = stats["bid_depth_1pct"] + stats["ask_depth_1pct"]
        if total_depth > 0:
            imbalance = float((stats["bid_depth_1pct"] - stats["ask_depth_1pct"]) / total_depth)
        else:
            imbalance = 0.0

        bids_raw = [[str(price), str(bids_dict[price])] for price in bid_prices]
        asks_raw = [[str(price), str(asks_dict[price])] for price in ask_prices]

        return {
            "exchange": self._exchange_name(),
            "symbol": symbol,
            "timestamp": timestamp,
            "last_update_id": last_update_id,
            "transaction_time": timestamp,
            "depth": len(bids),
            "mid_price": Decimal(str(mid_price)),
            "spread": Decimal(str(spread)),
            "spread_bps": Decimal(str(round(spread_bps, 4))),
            "bid1_price": Decimal(str(bid1_price)),
            "bid1_size": Decimal(str(bid1_size)),
            "ask1_price": Decimal(str(ask1_price)),
            "ask1_size": Decimal(str(ask1_size)),
            "bid_depth_1pct": stats["bid_depth_1pct"],
            "ask_depth_1pct": stats["ask_depth_1pct"],
            "bid_depth_5pct": stats["bid_depth_5pct"],
            "ask_depth_5pct": stats["ask_depth_5pct"],
            "bid_notional_1pct": stats["bid_notional_1pct"],
            "ask_notional_1pct": stats["ask_notional_1pct"],
            "bid_notional_5pct": stats["bid_notional_5pct"],
            "ask_notional_5pct": stats["ask_notional_5pct"],
            "imbalance": Decimal(str(round(imbalance, 6))),
            "bids": json.dumps(bids_raw),
            "asks": json.dumps(asks_raw),
            "source": self._source_name(),
            "source_event_time": timestamp,
        }

    async def _on_book(self, book, receipt_ts):
        if self._stop_event.is_set():
            return

        symbol = self._symbols.get(getattr(book, "symbol", ""))
        payload = getattr(book, "book", None)
        if not symbol or payload is None:
            return

        bids_side = getattr(payload, "bids", None)
        asks_side = getattr(payload, "asks", None)
        if bids_side is None or asks_side is None:
            return

        bids_dict = bids_side.to_dict()
        asks_dict = asks_side.to_dict()
        if not bids_dict or not asks_dict:
            return

        book_timestamp = getattr(book, "timestamp", 0) or receipt_ts or time.time()
        timestamp = datetime.utcfromtimestamp(book_timestamp)
        last_update_id = getattr(book, "sequence_number", None)
        previous_sequence = self._last_seq.get(symbol)
        if previous_sequence is not None and last_update_id is not None and last_update_id < previous_sequence:
            self._metrics.inc("orderbook_out_of_order")
            return
        if last_update_id is not None:
            self._last_seq[symbol] = last_update_id

        now = time.time()
        tick_rows = None
        full_rows = None
        with self._buffer_lock:
            if now - self._last_tick.get(symbol, 0) >= self._tick_interval_seconds():
                self._last_tick[symbol] = now
                tick_row = self._build_tick_row(symbol, timestamp, bids_dict, asks_dict)
                if tick_row is not None:
                    self._tick_buffer.append(tick_row)

            if now - self._last_full.get(symbol, 0) >= self._full_interval_seconds():
                self._last_full[symbol] = now
                full_row = self._build_full_row(symbol, timestamp, bids_dict, asks_dict, last_update_id=last_update_id)
                if full_row is not None:
                    self._full_buffer.append(full_row)

            if len(self._tick_buffer) >= self.MAX_TICK_BUFFER or len(self._full_buffer) >= self.MAX_FULL_BUFFER:
                if self._flush_timer is not None:
                    self._flush_timer.cancel()
                    self._flush_timer = None
                tick_rows, full_rows = self._drain_buffers_locked()
            else:
                self._schedule_flush_locked()

        if tick_rows or full_rows:
            self._write_buffers(tick_rows, full_rows)

    def run(self):
        if not getattr(self._config.crypto_orderbook, "enabled", True):
            logger.info("crypto order book collector disabled by config")
            return

        from cryptofeed import FeedHandler
        from cryptofeed.defines import L2_BOOK
        from cryptofeed.exchanges import BinanceFutures

        handler = FeedHandler(config=build_feedhandler_config("cryptofeed_orderbook.log"))
        feed_kwargs = {
            "symbols": list(self._symbols.keys()),
            "channels": [L2_BOOK],
            "callbacks": {L2_BOOK: self._on_book},
            "timeout": 60,
        }
        apply_feed_proxies(feed_kwargs, getattr(self._config.runtime, "http_proxy", ""))

        feed = BinanceFutures(**feed_kwargs)
        attach_ws_proxy(feed, getattr(self._config.runtime, "http_proxy", ""))
        handler.add_feed(feed)
        self._handler = handler
        logger.info("start order book websocket symbols=%d", len(self._symbols))
        try:
            handler.run()
        finally:
            self._handler = None
            self._final_flush()
            self._stop_event.set()
            self._ts.close()

    def stop(self):
        self._stop_event.set()
        handler = self._handler
        if handler is not None and hasattr(handler, "stop"):
            handler.stop()

    def close(self):
        self.stop()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    OrderBookCollector().run()


__all__ = ["OrderBookCollector"]
