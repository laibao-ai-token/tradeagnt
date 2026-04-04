"""Crypto K-line collector for collector-service."""

from __future__ import absolute_import

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from src.adapters.cryptofeed import BinanceWSAdapter, CandleEvent, preload_symbols
from src.adapters.gate_spot import GateSpotCandle, fetch_spot_candles, to_candle_row
from src.adapters.metrics import metrics
from src.adapters.timescale import TimescaleAdapter
from src.config import load_config


logger = logging.getLogger(__name__)

try:
    from common.symbols import get_configured_symbols
except Exception:
    get_configured_symbols = None


def normalize_symbol(symbol):
    value = (symbol or "").upper().replace("/", "").replace(":", "").replace("-", "")
    return value if value.endswith("USDT") else None


def load_symbols(exchange):
    configured = []
    if get_configured_symbols is not None:
        try:
            configured = list(get_configured_symbols() or [])
        except Exception:
            configured = []
    if configured:
        return configured

    try:
        import ccxt
    except Exception as exc:
        logger.warning("ccxt import failed for %s: %s", exchange, exc)
        return []

    exchange_cls = getattr(ccxt, exchange, None)
    if exchange_cls is None:
        raise ValueError("unsupported exchange: {0}".format(exchange))

    client = exchange_cls({"enableRateLimit": True, "timeout": 30000, "options": {"defaultType": "swap"}})
    client.load_markets()
    symbols = []
    for market in client.markets.values():
        if market.get("swap") and market.get("settle") == "USDT" and market.get("linear"):
            symbols.append("{0}USDT".format(market.get("base")))
    return sorted(set(symbols))


class WSCollector(object):
    """Crypto WS / polling collector with minimal batch writes."""

    FLUSH_WINDOW = 3.0
    MAX_BUFFER = 1000
    DEFAULT_GATE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

    def __init__(self, config=None, timescale=None, metrics_client=None):
        self._config = config or load_config()
        self._ts = timescale or TimescaleAdapter()
        self._metrics = metrics_client or metrics
        self._symbols = self._load_symbols()
        self._gap_stop = threading.Event()
        self._buffer = []
        self._buffer_lock = threading.Lock()
        self._flush_timer = None
        self._ws = None

    def _configured_symbols(self):
        values = list(getattr(self._config.crypto_kline, "symbols", []) or [])
        if values:
            return values
        if get_configured_symbols is None:
            return []
        try:
            return list(get_configured_symbols() or [])
        except Exception:
            return []

    def _load_symbols(self):
        provider = getattr(self._config.crypto_kline, "provider", "binance_futures_ws")
        configured = self._configured_symbols()

        if provider == "gate_spot_poll":
            raw_symbols = configured or list(self.DEFAULT_GATE_SYMBOLS)
            mapping = {}
            for symbol in raw_symbols:
                normalized = normalize_symbol(symbol)
                if normalized:
                    mapping[normalized] = normalized
            logger.info("gate spot polling symbols=%d", len(mapping))
            return mapping

        raw_symbols = configured or load_symbols(getattr(self._config.crypto_kline, "ccxt_exchange", "binance"))
        mapping = {}
        for symbol in raw_symbols:
            normalized = normalize_symbol(symbol)
            if not normalized:
                continue
            mapping["{0}-USDT-PERP".format(normalized[:-4])] = normalized
        if not mapping:
            raise RuntimeError("no symbols available for crypto kline collector")
        preload_symbols(list(mapping.values()))
        logger.info("loaded futures symbols=%d", len(mapping))
        return mapping

    def _drain_buffer_locked(self):
        rows = list(self._buffer)
        self._buffer = []
        self._flush_timer = None
        return rows

    def _schedule_flush_locked(self):
        if self.FLUSH_WINDOW <= 0 or self._flush_timer is not None:
            return
        timer = threading.Timer(self.FLUSH_WINDOW, self._flush_buffer)
        timer.daemon = True
        self._flush_timer = timer
        timer.start()

    def _write_rows(self, rows):
        if not rows:
            return 0
        try:
            written = self._ts.upsert_candles("1m", rows)
        except Exception as exc:
            logger.error("crypto candle batch write failed: %s", exc)
            return 0
        self._metrics.inc("rows_written", written)
        logger.debug("wrote crypto candles rows=%d", written)
        return written

    def _flush_buffer(self):
        with self._buffer_lock:
            rows = self._drain_buffer_locked()
        return self._write_rows(rows)

    def _final_flush(self):
        with self._buffer_lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
            rows = self._drain_buffer_locked()
        return self._write_rows(rows)

    def _on_candle(self, event):
        symbol = self._symbols.get(getattr(event, "symbol", ""))
        if not symbol:
            return

        row = {
            "exchange": getattr(self._config.crypto_kline, "db_exchange", "binance_futures_um"),
            "symbol": symbol,
            "bucket_ts": datetime.utcfromtimestamp(getattr(event, "timestamp", 0)),
            "open": getattr(event, "open", 0.0),
            "high": getattr(event, "high", 0.0),
            "low": getattr(event, "low", 0.0),
            "close": getattr(event, "close", 0.0),
            "volume": getattr(event, "volume", 0.0),
            "quote_volume": self._optional_float(getattr(event, "quote_volume", None)),
            "trade_count": getattr(event, "trade_count", None) or 0,
            "is_closed": True,
            "source": getattr(self._config.crypto_kline, "ws_source", "binance_ws"),
            "taker_buy_volume": self._optional_float(getattr(event, "taker_buy_volume", None)),
            "taker_buy_quote_volume": self._optional_float(getattr(event, "taker_buy_quote_volume", None)),
        }

        rows_to_write = None
        with self._buffer_lock:
            self._buffer.append(row)
            if len(self._buffer) >= self.MAX_BUFFER:
                if self._flush_timer is not None:
                    self._flush_timer.cancel()
                    self._flush_timer = None
                rows_to_write = self._drain_buffer_locked()
            else:
                self._schedule_flush_locked()
        if rows_to_write:
            self._write_rows(rows_to_write)

    def _on_candle_sync(self, event):
        self._on_candle(event)

    def _optional_float(self, value):
        if value in (None, ""):
            return None
        return float(value)

    def _poll_gate_spot_once(self):
        symbols = list(self._symbols.values())
        if not symbols:
            return 0

        timeout_seconds = float(getattr(self._config.crypto_kline, "gate_timeout_seconds", 10))
        exchange = getattr(self._config.crypto_kline, "gate_db_exchange", "gate_spot")
        workers = max(1, int(getattr(self._config.crypto_kline, "gate_workers", 4)))
        rows = []

        def _fetch_one(symbol):
            base = symbol[:-4]
            pair = "{0}_USDT".format(base)
            candles = fetch_spot_candles(pair, interval="1m", limit=2, timeout_s=timeout_seconds)
            payload = []
            for candle in candles:
                if getattr(candle, "is_closed", False):
                    payload.append(to_candle_row(exchange=exchange, symbol=symbol, candle=candle, source="gate_spot"))
            return payload

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = dict((pool.submit(_fetch_one, symbol), symbol) for symbol in symbols)
            for future in as_completed(futures):
                try:
                    rows.extend(future.result())
                except Exception as exc:
                    logger.debug("gate spot fetch failed %s: %s", futures[future], exc)

        return self._write_rows(rows)

    def _run_gate_spot_poll(self):
        interval_seconds = max(1.0, float(getattr(self._config.crypto_kline, "gate_poll_interval_seconds", 10)))
        logger.info("start gate spot polling symbols=%d interval=%.1fs", len(self._symbols), interval_seconds)
        while not self._gap_stop.is_set():
            self._poll_gate_spot_once()
            if self._gap_stop.wait(interval_seconds):
                break

    def run(self):
        if not getattr(self._config.crypto_kline, "enabled", True):
            logger.info("crypto kline collector disabled by config")
            return

        provider = getattr(self._config.crypto_kline, "provider", "binance_futures_ws")
        if provider == "gate_spot_poll":
            self._gap_stop.clear()
            try:
                self._run_gate_spot_poll()
            finally:
                self._gap_stop.set()
                self._ts.close()
            return

        if not getattr(self._config.crypto_kline, "websocket_enabled", True):
            logger.info("crypto websocket collector disabled by config")
            self._ts.close()
            return

        ws = BinanceWSAdapter(http_proxy=getattr(self._config.runtime, "http_proxy", ""))
        self._ws = ws
        ws.subscribe(list(self._symbols.keys()), self._on_candle_sync)
        try:
            ws.run()
        finally:
            self._ws = None
            self._final_flush()
            self._gap_stop.set()
            self._ts.close()

    def stop(self):
        self._gap_stop.set()
        ws = self._ws
        if ws is not None and hasattr(ws, "stop"):
            ws.stop()

    def close(self):
        self.stop()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    WSCollector().run()


__all__ = [
    "BinanceWSAdapter",
    "CandleEvent",
    "GateSpotCandle",
    "WSCollector",
    "fetch_spot_candles",
    "load_symbols",
    "normalize_symbol",
    "preload_symbols",
    "to_candle_row",
]
