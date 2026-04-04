"""US equity collector backed by yfinance."""

from __future__ import absolute_import

import logging
import os
from datetime import datetime, timezone

from src.config import load_config
from src.core import BaseFetcher, ProviderRegistry, register_fetcher
from src.storage import batch as batch_module
from src.storage.raw_writer import TimescaleRawWriter

logger = logging.getLogger(__name__)


class EquityQuery(object):
    def __init__(self, market, symbol, interval="1m", limit=1, start=None, end=None):
        self.market = market
        self.symbol = symbol
        self.interval = interval or "1m"
        self.limit = int(limit or 1)
        self.start = start
        self.end = end


def _normalize_timestamp(value):
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@register_fetcher("yfinance", "candle")
class YFinanceCandleFetcher(BaseFetcher):
    """Minimal yfinance fetcher that returns raw-writer compatible rows."""

    INTERVAL_MAP = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "60m",
        "1d": "1d",
    }

    def __init__(self, config=None, client_factory=None):
        self._config = config or load_config()
        self._client_factory = client_factory or self._default_client_factory
        proxy = getattr(getattr(self._config, "runtime", object()), "http_proxy", "") or ""
        if proxy:
            os.environ.setdefault("HTTP_PROXY", proxy)
            os.environ.setdefault("HTTPS_PROXY", proxy)

    @staticmethod
    def _default_client_factory(symbol):
        import yfinance as yf

        return yf.Ticker(symbol)

    def transform_query(self, params):
        return EquityQuery(**params)

    async def extract(self, query):
        ticker = self._client_factory(query.symbol)
        interval = self.INTERVAL_MAP.get(query.interval, "1m")
        frame = ticker.history(start=query.start, end=query.end, interval=interval)
        if frame is None or getattr(frame, "empty", False):
            return []
        if hasattr(frame, "reset_index"):
            frame = frame.reset_index()
        if query.limit and hasattr(frame, "tail") and len(frame) > query.limit:
            frame = frame.tail(query.limit)
        rows = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame or [])
        for row in rows:
            row["_market"] = query.market
            row["_symbol"] = query.symbol
            row["_interval"] = query.interval
        return rows

    def transform_data(self, raw):
        rows = []
        for row in list(raw or []):
            ts = _normalize_timestamp(row.get("Datetime") or row.get("Date") or row.get("timestamp"))
            if ts is None:
                continue
            rows.append(
                {
                    "exchange": "us",
                    "symbol": str(row.get("_symbol") or row.get("symbol") or ""),
                    "open_time": ts,
                    "close_time": None,
                    "open": float(row.get("Open", row.get("open", 0)) or 0),
                    "high": float(row.get("High", row.get("high", 0)) or 0),
                    "low": float(row.get("Low", row.get("low", 0)) or 0),
                    "close": float(row.get("Close", row.get("close", 0)) or 0),
                    "volume": float(row.get("Volume", row.get("volume", 0)) or 0),
                    "amount": None,
                    "source": "yfinance",
                    "source_event_time": ts,
                }
            )
        return rows


class USEquityCollector(object):
    """Minimal US equity collector with batch write integration."""

    MARKET = "us_stock"
    MARKET_CODE = "us"
    PROVIDER_ATTR = "us_provider"
    SYMBOLS_ATTR = "us_symbols"
    DEFAULT_PROVIDER = "yfinance"

    def __init__(self, config=None, writer=None, batch_start=None, fetcher=None):
        self._config = config or load_config()
        self._writer = writer or TimescaleRawWriter()
        self._batch_start = batch_start or batch_module.start_batch
        self._fetcher = fetcher
        self._runtime_fetcher = None
        self._owns_writer = writer is None

    def _provider_name(self):
        return getattr(self._config.equity, self.PROVIDER_ATTR, self.DEFAULT_PROVIDER) or self.DEFAULT_PROVIDER

    def _symbols(self, symbols=None):
        values = list(symbols or getattr(self._config.equity, self.SYMBOLS_ATTR, []) or [])
        return [str(value).strip() for value in values if str(value).strip()]

    def _fetcher_instance(self):
        if self._fetcher is not None:
            return self._fetcher
        if self._runtime_fetcher is not None:
            return self._runtime_fetcher
        provider_name = self._provider_name()
        fetcher_cls = ProviderRegistry.get(provider_name, "candle")
        if fetcher_cls is None and provider_name == "yfinance":
            fetcher_cls = YFinanceCandleFetcher
        if fetcher_cls is None:
            raise ValueError("Provider not registered: {0}".format(provider_name))
        self._runtime_fetcher = fetcher_cls(config=self._config)
        return self._runtime_fetcher

    def collect(self, symbols=None):
        markets = list(getattr(self._config.equity, "markets", []) or [])
        if markets and self.MARKET_CODE not in markets:
            return []

        interval = getattr(self._config.equity, "interval", "1m") or "1m"
        limit = int(getattr(self._config.equity, "limit", 1) or 1)
        fetcher = self._fetcher_instance()
        rows = []
        for symbol in self._symbols(symbols):
            rows.extend(fetcher.fetch_sync(market=self.MARKET, symbol=symbol, interval=interval, limit=limit))
        return rows

    def save(self, rows):
        if not rows:
            return 0
        provider = self._provider_name()
        batch_id = self._batch_start(source="{0}_equity_poll".format(provider), data_type="equity_1m", market=self.MARKET)
        return self._writer.upsert_equity_1m(self.MARKET, rows, ingest_batch_id=batch_id, source=provider)

    def run_once(self, symbols=None):
        if not getattr(self._config.equity, "enabled", False):
            logger.info("equity collector disabled by config")
            return 0
        return self.save(self.collect(symbols=symbols))

    def close(self):
        if self._owns_writer and hasattr(self._writer, "close"):
            self._writer.close()
