"""Cryptofeed adapter for Binance futures candle stream."""

from __future__ import absolute_import

import copy
import logging
import os
from decimal import Decimal

from src.config import SERVICE_ROOT


logger = logging.getLogger(__name__)


def _decimal_or_zero(value):
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def build_feedhandler_config(log_filename):
    log_dir = os.path.join(str(SERVICE_ROOT), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return {
        "uvloop": False,
        "log": {
            "filename": os.path.join(log_dir, log_filename),
            "level": "INFO",
        },
    }


def apply_feed_proxies(feed_kwargs, http_proxy=None):
    proxy = (http_proxy or "").strip()
    if not proxy:
        return feed_kwargs

    feed_kwargs["http_proxy"] = proxy
    return feed_kwargs


def attach_ws_proxy(feed, http_proxy=None):
    proxy = (http_proxy or "").strip()
    if not proxy:
        return feed

    endpoints = list(getattr(feed, "websocket_endpoints", []) or [])
    if not endpoints:
        return feed

    feed.websocket_endpoints = []
    for endpoint in endpoints:
        cloned = copy.deepcopy(endpoint)
        cloned.options = dict(getattr(cloned, "options", {}) or {})
        cloned.options["proxy"] = proxy
        feed.websocket_endpoints.append(cloned)
    return feed


class CandleEvent(object):
    """Normalized closed-candle event."""

    def __init__(
        self,
        symbol,
        timestamp,
        open,
        high,
        low,
        close,
        volume,
        quote_volume=None,
        taker_buy_volume=None,
        taker_buy_quote_volume=None,
        trade_count=None,
    ):
        self.symbol = symbol
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.quote_volume = quote_volume
        self.taker_buy_volume = taker_buy_volume
        self.taker_buy_quote_volume = taker_buy_quote_volume
        self.trade_count = trade_count


class BinanceWSAdapter(object):
    """Thin wrapper around cryptofeed Binance futures candles."""

    def __init__(self, http_proxy=None):
        self._proxy = http_proxy
        self._handler = None
        self._callback = None
        self._symbols = []

    def subscribe(self, symbols, callback):
        self._symbols = list(symbols or [])
        self._callback = callback

    async def _on_candle(self, candle, receipt_ts):
        del receipt_ts
        if not getattr(candle, "closed", False) or self._callback is None:
            return

        raw = getattr(candle, "raw", {}) or {}
        payload = raw.get("k", {}) if isinstance(raw, dict) else {}
        self._callback(
            CandleEvent(
                symbol=getattr(candle, "symbol", ""),
                timestamp=getattr(candle, "start", 0),
                open=getattr(candle, "open", 0.0),
                high=getattr(candle, "high", 0.0),
                low=getattr(candle, "low", 0.0),
                close=getattr(candle, "close", 0.0),
                volume=getattr(candle, "volume", 0.0),
                quote_volume=_decimal_or_zero(payload.get("q", "0")),
                taker_buy_volume=_decimal_or_zero(payload.get("V", "0")),
                taker_buy_quote_volume=_decimal_or_zero(payload.get("Q", "0")),
                trade_count=getattr(candle, "trades", None),
            )
        )

    def run(self):
        from cryptofeed import FeedHandler
        from cryptofeed.defines import CANDLES
        from cryptofeed.exchanges import BinanceFutures

        handler = FeedHandler(config=build_feedhandler_config("cryptofeed_kline.log"))
        feed_kwargs = {
            "symbols": self._symbols,
            "channels": [CANDLES],
            "callbacks": {CANDLES: self._on_candle},
            "candle_interval": "1m",
            "candle_closed_only": True,
            "timeout": 60,
        }
        apply_feed_proxies(feed_kwargs, self._proxy)

        feed = BinanceFutures(**feed_kwargs)
        attach_ws_proxy(feed, self._proxy)
        handler.add_feed(feed)
        self._handler = handler
        logger.info("start binance futures websocket symbols=%d", len(self._symbols))
        handler.run()

    def stop(self):
        if self._handler is not None:
            self._handler.stop()


def preload_symbols(symbols):
    try:
        from cryptofeed.defines import BINANCE_FUTURES
        from cryptofeed.defines import PERPETUAL
        from cryptofeed.exchanges import BinanceFutures
        from cryptofeed.symbols import Symbol, Symbols
    except Exception as exc:
        logger.warning("preload cryptofeed symbols skipped: %s", exc)
        return

    mapping = {}
    for symbol in list(symbols or []):
        upper = (symbol or "").upper()
        if not upper.endswith("USDT"):
            continue
        normalized = Symbol(upper[:-4], "USDT", type=PERPETUAL).normalized
        mapping[normalized] = upper

    if not mapping:
        return

    Symbols.set(
        BINANCE_FUTURES,
        mapping,
        {
            "symbols": list(mapping.keys()),
            "channels": {
                "rest": [],
                "websocket": list(BinanceFutures.websocket_channels.keys()),
            },
        },
    )
    logger.info("preloaded cryptofeed symbols=%d", len(mapping))
