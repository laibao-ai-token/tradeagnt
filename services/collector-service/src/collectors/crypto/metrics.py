"""Crypto futures metrics collector for collector-service."""

from __future__ import absolute_import

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal

import requests

from src.adapters.metrics import Timer, metrics
from src.adapters.timescale import TimescaleAdapter
from src.config import load_config
from src.collectors.crypto.ws import load_symbols


logger = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"


def _to_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _first_record(payload):
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    return first if isinstance(first, dict) else None


def _build_session():
    adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class MetricsCollector(object):
    """Binance futures metrics collector with minimal config integration."""

    def __init__(self, config=None, timescale=None, session=None, metrics_client=None, workers=8):
        self._config = config or load_config()
        self._ts = timescale or TimescaleAdapter()
        self._metrics = metrics_client or metrics
        self._workers = int(workers)
        self._session = session or _build_session()
        self._owns_session = session is None
        proxy = getattr(self._config.runtime, "http_proxy", "") or ""
        self._proxies = {"http": proxy, "https": proxy} if proxy else {}

    def _period(self):
        return getattr(self._config.crypto_metrics, "interval", "5m") or "5m"

    def _db_exchange(self):
        return getattr(self._config.crypto_kline, "db_exchange", "binance_futures_um")

    def _ccxt_exchange(self):
        return getattr(self._config.crypto_kline, "ccxt_exchange", "binance")

    def _get(self, url, params):
        self._metrics.inc("requests_total")
        try:
            response = self._session.get(url, params=params, proxies=self._proxies, timeout=10)
            if response.status_code in (418, 429):
                self._metrics.inc("requests_failed")
                logger.warning("metrics request throttled status=%s symbol=%s", response.status_code, params.get("symbol"))
                return None
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            self._metrics.inc("requests_failed")
            logger.debug("metrics request failed symbol=%s error=%s", params.get("symbol"), exc)
            return None

    def _collect_one(self, symbol):
        sym = (symbol or "").upper()
        period = self._period()
        apis = [
            ("oi", "{0}/futures/data/openInterestHist".format(FAPI), {"symbol": sym, "period": period, "limit": 1}),
            (
                "pos",
                "{0}/futures/data/topLongShortPositionRatio".format(FAPI),
                {"symbol": sym, "period": period, "limit": 1},
            ),
            (
                "acc",
                "{0}/futures/data/topLongShortAccountRatio".format(FAPI),
                {"symbol": sym, "period": period, "limit": 1},
            ),
            (
                "glb",
                "{0}/futures/data/globalLongShortAccountRatio".format(FAPI),
                {"symbol": sym, "period": period, "limit": 1},
            ),
            (
                "taker",
                "{0}/futures/data/takerlongshortRatio".format(FAPI),
                {"symbol": sym, "period": period, "limit": 1},
            ),
        ]

        results = {}
        for key, url, params in apis:
            results[key] = self._get(url, params)

        oi = _first_record(results.get("oi"))
        pos = _first_record(results.get("pos"))
        acc = _first_record(results.get("acc"))
        glb = _first_record(results.get("glb"))
        taker = _first_record(results.get("taker"))

        if oi is None:
            return None

        timestamp = int(oi.get("timestamp", 0))
        timestamp = (timestamp // 300000) * 300000

        return {
            "create_time": datetime.utcfromtimestamp(timestamp / 1000),
            "symbol": sym,
            "exchange": self._db_exchange(),
            "sum_open_interest": _to_decimal(oi.get("sumOpenInterest")),
            "sum_open_interest_value": _to_decimal(oi.get("sumOpenInterestValue")),
            "count_toptrader_long_short_ratio": _to_decimal(acc.get("longShortRatio")) if acc else None,
            "sum_toptrader_long_short_ratio": _to_decimal(pos.get("longShortRatio")) if pos else None,
            "count_long_short_ratio": _to_decimal(glb.get("longShortRatio")) if glb else None,
            "sum_taker_long_short_vol_ratio": _to_decimal(taker.get("buySellRatio")) if taker else None,
            "source": "binance_api",
            "is_closed": True,
        }

    def collect(self, symbols):
        rows = []
        with ThreadPoolExecutor(max_workers=max(1, self._workers)) as pool:
            futures = dict((pool.submit(self._collect_one, symbol), symbol) for symbol in list(symbols or []))
            for future in as_completed(futures):
                try:
                    row = future.result()
                    if row:
                        rows.append(row)
                except Exception as exc:
                    logger.debug("metrics collect failed symbol=%s error=%s", futures[future], exc)
        return rows

    def save(self, rows):
        if not rows:
            return 0
        written = self._ts.upsert_metrics(rows)
        self._metrics.inc("rows_written", written)
        return written

    def run_once(self, symbols=None):
        if not getattr(self._config.crypto_metrics, "enabled", False):
            logger.info("crypto metrics collector disabled by config")
            return 0

        resolved_symbols = list(symbols or load_symbols(self._ccxt_exchange()))
        logger.info("collect crypto metrics symbols=%d workers=%d", len(resolved_symbols), self._workers)
        with Timer("last_collect_duration", metrics_client=self._metrics):
            rows = self.collect(resolved_symbols)
            written = self.save(rows)
        logger.info("saved metrics rows=%d | %s", written, self._metrics)
        return written

    def close(self):
        try:
            self._ts.close()
        finally:
            if self._owns_session and hasattr(self._session, "close"):
                self._session.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    collector = MetricsCollector()
    try:
        collector.run_once()
    finally:
        collector.close()


__all__ = ["MetricsCollector", "FAPI"]
