"""HK equity collector backed by Tencent quote snapshots."""

from __future__ import absolute_import

import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal

from src.config import load_config
from src.core import BaseFetcher, ProviderRegistry, register_fetcher
from src.storage import batch as batch_module
from src.storage.raw_writer import TimescaleRawWriter

logger = logging.getLogger(__name__)

HK_TS_RE = re.compile(r"^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}$")


class EquityQuery(object):
    def __init__(self, market, symbol, interval="1m", limit=1, start=None, end=None):
        self.market = market
        self.symbol = symbol
        self.interval = interval or "1m"
        self.limit = int(limit or 1)
        self.start = start
        self.end = end


class QuotePoint(object):
    def __init__(self, symbol, ts_utc, last, cum_volume):
        self.symbol = symbol
        self.ts_utc = ts_utc
        self.last = last
        self.cum_volume = cum_volume


def _normalize_hk_symbol(symbol):
    value = str(symbol or "").strip()
    if "." in value:
        value = value.split(".", 1)[0]
    if value.isdigit() and len(value) < 5:
        value = value.zfill(5)
    return value


def _build_hk_code(symbol):
    normalized = _normalize_hk_symbol(symbol)
    return "hk{0}".format(normalized), normalized


def _parse_point(value, symbol):
    fields = str(value or "").split("~")
    if len(fields) < 7:
        return None

    try:
        last = Decimal(str(fields[3]))
        cum_volume = Decimal(str(fields[6]))
    except Exception:
        return None

    ts_field = None
    for field in fields:
        if HK_TS_RE.match(field):
            ts_field = field
            break
    if not ts_field:
        return None

    local_time = datetime.strptime(ts_field, "%Y/%m/%d %H:%M:%S")
    ts_utc = local_time - timedelta(hours=8)
    return QuotePoint(symbol=symbol, ts_utc=ts_utc, last=last, cum_volume=cum_volume)


def _default_fetch_var(code):
    import requests

    response = requests.get("https://qt.gtimg.cn/q={0}".format(code), timeout=20)
    response.raise_for_status()
    response.encoding = "gbk"
    text = response.text.strip()
    if not text:
        return ""
    if '"' in text:
        parts = text.split('"')
        if len(parts) >= 2:
            return parts[1]
    return ""


@register_fetcher("tencent", "candle")
class TencentHKQuoteFetcher(BaseFetcher):
    """Minimal Tencent snapshot fetcher that emits 1m HK candles."""

    def __init__(self, config=None, fetch_var=None):
        self._config = config or load_config()
        self._fetch_var = fetch_var or _default_fetch_var
        self._state = {}

    def transform_query(self, params):
        return EquityQuery(**params)

    async def extract(self, query):
        if query.market != "hk_stock" or query.interval != "1m":
            return []

        code, symbol = _build_hk_code(query.symbol)
        try:
            value = self._fetch_var(code)
        except Exception:
            return []

        point = _parse_point(value, symbol)
        if point is None:
            return []

        minute_open = point.ts_utc.replace(second=0, microsecond=0)
        state = self._state.get(symbol)
        if state and state["minute_open"] == minute_open:
            state["high"] = max(state["high"], point.last)
            state["low"] = min(state["low"], point.last)
            state["close"] = point.last
            delta = point.cum_volume - state["cum_volume"]
            if delta < 0:
                delta = Decimal("0")
            state["minute_volume"] += delta
            state["cum_volume"] = point.cum_volume
        else:
            minute_volume = Decimal("0")
            if state is not None:
                delta = point.cum_volume - state["cum_volume"]
                if delta > 0:
                    minute_volume = delta
            state = {
                "minute_open": minute_open,
                "open": point.last,
                "high": point.last,
                "low": point.last,
                "close": point.last,
                "cum_volume": point.cum_volume,
                "minute_volume": minute_volume,
                "source_event_time": point.ts_utc,
            }
            self._state[symbol] = state

        return [
            {
                "exchange": "hkex",
                "symbol": symbol,
                "open_time": state["minute_open"],
                "close_time": None,
                "open": float(state["open"]),
                "high": float(state["high"]),
                "low": float(state["low"]),
                "close": float(state["close"]),
                "volume": float(state["minute_volume"]),
                "amount": None,
                "source": "tencent",
                "source_event_time": state["source_event_time"],
            }
        ]

    def transform_data(self, raw):
        return [dict(row) for row in list(raw or [])]


class HKEquityCollector(object):
    """Minimal HK equity collector with batch write integration."""

    MARKET = "hk_stock"
    MARKET_CODE = "hk"
    PROVIDER_ATTR = "hk_provider"
    SYMBOLS_ATTR = "hk_symbols"
    DEFAULT_PROVIDER = "tencent"

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
        if fetcher_cls is None and provider_name == "tencent":
            fetcher_cls = TencentHKQuoteFetcher
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
            if limit and len(rows) >= limit:
                rows = rows[-limit:]
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
