"""Minimal exchange-traded CN fund collector."""

from __future__ import absolute_import

import logging

from src.adapters.tencent import fetch_tencent_cn_quotes
from src.config import load_config
from src.collectors.fund.symbols import cn_fund_exchange_candidates, normalize_cn_fund_symbol

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 3.0


def _proxy_from_config(config):
    runtime = getattr(config, "runtime", object())
    return getattr(runtime, "http_proxy", "") or ""


class ETFFundCollector(object):
    """Fetch ETF/LOF-like CN fund snapshots from Tencent."""

    def __init__(self, config=None, fetch_quotes=None, timeout_s=DEFAULT_TIMEOUT_SECONDS, writer=None):
        self._config = config or load_config()
        self._fetch_quotes = fetch_quotes or fetch_tencent_cn_quotes
        self._timeout_s = float(timeout_s)
        self._writer = writer

    def _symbols(self, symbols=None):
        values = list(symbols or getattr(self._config.fund_cn, "etf_symbols", []) or [])
        normalized = []
        seen = set()
        for value in values:
            symbol = normalize_cn_fund_symbol(value)
            if not symbol or symbol in seen:
                continue
            normalized.append(symbol)
            seen.add(symbol)
        return normalized

    def collect(self, symbols=None):
        ordered_inputs = self._symbols(symbols=symbols)
        if not ordered_inputs:
            return []

        queries = []
        query_map = {}
        for symbol in ordered_inputs:
            candidates = cn_fund_exchange_candidates(symbol)
            if not candidates:
                continue
            query_map[symbol] = list(candidates)
            for candidate in candidates:
                if candidate not in queries:
                    queries.append(candidate)
        if not queries:
            return []

        try:
            quotes = self._fetch_quotes(queries, timeout_s=self._timeout_s, proxy=_proxy_from_config(self._config)) or {}
        except Exception as exc:
            logger.warning("fund_cn etf fetch failed symbols=%s error=%s", ",".join(queries), exc)
            return []
        rows = []
        for symbol in ordered_inputs:
            quote = None
            for candidate in query_map.get(symbol, []):
                item = quotes.get(candidate)
                if item is not None and float(item.get("price") or 0.0) > 0:
                    quote = dict(item)
                    break
            if quote is not None:
                rows.append(quote)
        return rows

    def save(self, rows, batch_id):
        """Write collected rows to database."""
        if not self._writer or not rows:
            return 0
        try:
            return self._writer.upsert_fund_cn_etf(rows, batch_id, source="tencent")
        except Exception as exc:
            logger.warning("fund_cn etf save failed error=%s", exc)
            return 0

    def run_once(self, symbols=None, batch_id=None):
        if not getattr(self._config.fund_cn, "enabled", False):
            logger.info("fund_cn etf collector disabled by config")
            return 0
        rows = self.collect(symbols=symbols)
        if rows and batch_id and self._writer:
            self.save(rows, batch_id)
        return len(rows)

    def close(self):
        return None
