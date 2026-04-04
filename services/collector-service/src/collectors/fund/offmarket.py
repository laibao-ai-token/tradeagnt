"""Minimal off-market CN fund valuation collector."""

from __future__ import absolute_import

import logging

from src.adapters.eastmoney import SAFE_CN_FUND_CODE_RE, fetch_fundgz_quote
from src.config import load_config
from src.collectors.fund.symbols import normalize_cn_fund_symbol

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 3.0


def _proxy_from_config(config):
    runtime = getattr(config, "runtime", object())
    return getattr(runtime, "http_proxy", "") or ""


class OffMarketFundCollector(object):
    """Fetch off-market CN fund valuation snapshots from Eastmoney."""

    def __init__(self, config=None, fetch_quote=None, timeout_s=DEFAULT_TIMEOUT_SECONDS, writer=None):
        self._config = config or load_config()
        self._fetch_quote = fetch_quote or fetch_fundgz_quote
        self._timeout_s = float(timeout_s)
        self._writer = writer

    def _codes(self, codes=None):
        values = list(codes or getattr(self._config.fund_cn, "offmarket_codes", []) or [])
        normalized = []
        seen = set()
        for value in values:
            code = normalize_cn_fund_symbol(value)
            if not SAFE_CN_FUND_CODE_RE.match(code) or code in seen:
                continue
            normalized.append(code)
            seen.add(code)
        return normalized

    def collect(self, codes=None):
        rows = []
        for code in self._codes(codes=codes):
            try:
                quote = self._fetch_quote(code, timeout_s=self._timeout_s, proxy=_proxy_from_config(self._config))
            except Exception as exc:
                logger.warning("fund_cn offmarket fetch failed code=%s error=%s", code, exc)
                continue
            if quote is None:
                continue
            rows.append(dict(quote))
        return rows

    def run_once(self, codes=None, batch_id=None, writer=None):
        """Run collector once and optionally save to database.

        Args:
            codes: Optional fund code list. If None, use config default.
            batch_id: Required for database write. If None, no persistence.
            writer: Optional writer instance. If None, uses injected writer.

        Returns:
            Number of rows saved.
        """
        if not getattr(self._config.fund_cn, "enabled", False):
            logger.info("fund_cn offmarket collector disabled by config")
            return 0

        # Collect data
        rows = self.collect(codes=codes)

        # Save to database if writer is provided
        effective_writer = writer or self._writer
        if effective_writer and rows and batch_id:
            try:
                saved = effective_writer.upsert_fund_cn_offmarket(rows, batch_id, source="fundgz")
                logger.info("fund_cn offmarket saved %d rows", saved)
                return saved
            except Exception as exc:
                logger.warning("fund_cn offmarket save failed error=%s", exc)
                return 0

        return len(rows)

    def close(self):
        return None
