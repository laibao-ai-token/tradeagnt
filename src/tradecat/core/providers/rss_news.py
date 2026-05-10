"""RSS news provider (alternative data)."""
from __future__ import annotations

import re
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
        """RSS does not provide OHLCV → return empty DataFrame with correct schema."""
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
        keyword = symbol.upper().replace("USDT", "").replace("_USDT", "")
        results: list[dict] = []
        for url in self._feeds:
            try:
                resp = await self._client.get(url)
                items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
                for item in items[:limit]:
                    title = re.search(r"<title>(.*?)</title>", item)
                    link = re.search(r"<link>(.*?)</link>", item)
                    pub = re.search(r"<pubDate>(.*?)</pubDate>", item)
                    t = (title.group(1) if title else "").lower()
                    if keyword.lower() in t:
                        results.append({
                            "title": title.group(1) if title else "",
                            "link": link.group(1) if link else "",
                            "published": pub.group(1) if pub else "",
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
