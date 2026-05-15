"""RSS news provider (alternative data)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd

from tradecat.core.providers.base import DataProvider


class RSSNewsProvider(DataProvider):
    """Light-weight RSS news fetcher for sentiment data."""

    def __init__(self, feeds: list[str] | None = None) -> None:
        self._feeds = feeds or []
        self._client = httpx.AsyncClient(timeout=30)

    @property
    def name(self) -> str:
        return "rss_news"

    async def fetch_klines(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> pd.DataFrame:
        """RSS does not provide OHLCV → return empty DataFrame."""
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

    async def fetch_latest(self, symbol: str) -> dict[str, Any]:
        articles = await self._fetch_articles(symbol, limit=5)
        return {
            "symbol": symbol,
            "articles": articles,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": len(articles),
        }

    async def _fetch_articles(self, symbol: str, limit: int = 5) -> list[dict]:
        keyword = re.sub(r"[-_]?USDT$", "", symbol.upper())
        results: list[dict] = []
        for url in self._feeds:
            try:
                resp = await self._client.get(url)
                root = ET.fromstring(resp.text)
                items = root.findall(".//item")
                for item in items[:limit]:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    pub_el = item.find("pubDate")
                    title = (
                        (title_el.text or "")
                        if title_el is not None else ""
                    )
                    link = (
                        (link_el.text or "")
                        if link_el is not None else ""
                    )
                    pub = (
                        (pub_el.text or "")
                        if pub_el is not None else ""
                    )
                    if keyword.lower() in title.lower():
                        results.append({
                            "title": title,
                            "link": link,
                            "published": pub,
                        })
            except Exception:
                continue
        return results

    def supported_symbols(self) -> list[str]:
        return ["*"]

    def can_resolve(self, symbol: str) -> bool:
        return True

    async def close(self) -> None:
        await self._client.aclose()
