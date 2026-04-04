"""CN equity collector backed by AKShare."""

from __future__ import absolute_import

import logging
import os
from datetime import datetime, timedelta

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


def _normalize_cn_symbol(symbol):
    value = str(symbol or "").strip()
    if "." in value:
        value = value.split(".", 1)[0]
    if len(value) >= 8 and value[:2].upper() in ("SZ", "SH") and value[2:].isdigit():
        return value[2:]
    return value


def _detect_exchange(symbol):
    raw = str(symbol or "").upper()
    if raw.endswith(".SZ") or raw.startswith("SZ"):
        return "szse"
    if raw.endswith(".SH") or raw.startswith("SH"):
        return "sse"
    base = _normalize_cn_symbol(symbol)
    return "sse" if base[:1] in ("5", "6", "9") else "szse"


def _parse_cn_timestamp(value):
    if isinstance(value, datetime):
        dt_value = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) == 10:
            dt_value = datetime.strptime(text, "%Y-%m-%d")
        else:
            dt_value = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return dt_value - timedelta(hours=8)


@register_fetcher("akshare", "candle")
class AKShareCandleFetcher(BaseFetcher):
    """Minimal AKShare fetcher for A-share minute candles."""

    MINUTE_PERIOD_MAP = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "60m": "60",
    }

    def __init__(self, config=None, api=None):
        self._config = config or load_config()
        self._api = api or self._default_api()
        proxy = getattr(getattr(self._config, "runtime", object()), "http_proxy", "") or ""
        if proxy:
            os.environ.setdefault("HTTP_PROXY", proxy)
            os.environ.setdefault("HTTPS_PROXY", proxy)

    @staticmethod
    def _default_api():
        import akshare

        return akshare

    def transform_query(self, params):
        return EquityQuery(**params)

    async def extract(self, query):
        if query.market != "cn_stock":
            return []

        symbol = _normalize_cn_symbol(query.symbol)
        period = self.MINUTE_PERIOD_MAP.get(query.interval, "1")
        start_date = query.start.strftime("%Y-%m-%d %H:%M:%S") if query.start else "1970-01-01 00:00:00"
        end_date = query.end.strftime("%Y-%m-%d %H:%M:%S") if query.end else datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        try:
            frame = self._api.stock_zh_a_hist_min_em(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                period=period,
                adjust="",
            )
        except TypeError:
            frame = self._api.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust="")

        if frame is None or getattr(frame, "empty", False):
            return []
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
            ts = _parse_cn_timestamp(row.get("时间") or row.get("日期") or row.get("datetime"))
            if ts is None:
                continue
            rows.append(
                {
                    "exchange": _detect_exchange(row.get("_symbol") or row.get("symbol")),
                    "symbol": _normalize_cn_symbol(row.get("_symbol") or row.get("symbol")),
                    "open_time": ts,
                    "close_time": None,
                    "open": float(row.get("开盘", row.get("open", 0)) or 0),
                    "high": float(row.get("最高", row.get("high", 0)) or 0),
                    "low": float(row.get("最低", row.get("low", 0)) or 0),
                    "close": float(row.get("收盘", row.get("close", 0)) or 0),
                    "volume": float(row.get("成交量", row.get("volume", 0)) or 0),
                    "amount": float(row.get("成交额", 0) or 0) if row.get("成交额") is not None else None,
                    "source": "akshare",
                    "source_event_time": ts,
                }
            )
        return rows


class CNEquityCollector(object):
    """Minimal CN equity collector with batch write integration."""

    MARKET = "cn_stock"
    MARKET_CODE = "cn"
    PROVIDER_ATTR = "cn_provider"
    SYMBOLS_ATTR = "cn_symbols"
    DEFAULT_PROVIDER = "akshare"

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
        if fetcher_cls is None and provider_name == "akshare":
            fetcher_cls = AKShareCandleFetcher
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
