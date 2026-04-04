"""RSS/Atom news collector for collector-service."""

from __future__ import absolute_import

import hashlib
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from src.config import load_config
from src.core import BaseFetcher, ProviderRegistry, register_fetcher
from src.storage import batch as batch_module
from src.storage.news_writer import TimescaleNewsWriter

logger = logging.getLogger(__name__)

UTC = timezone.utc
TAG_RE = re.compile(r"<[^>]+>")


class NewsQuery(object):
    def __init__(self, feeds=None, limit=100, window_hours=72, timeout_s=20):
        self.feeds = list(feeds or [])
        self.limit = int(limit or 100)
        self.window_hours = int(window_hours or 72)
        self.timeout_s = int(timeout_s or 20)


def _parse_feeds(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]

    feeds = []
    seen = set()
    for part in str(value).replace("\n", ",").split(","):
        item = part.strip()
        if not item or item in seen:
            continue
        feeds.append(item)
        seen.add(item)
    return feeds


def _local(tag):
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _text(element):
    return (getattr(element, "text", "") or "").strip() if element is not None else ""


def _strip_html(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    return " ".join(TAG_RE.sub(" ", html.unescape(raw)).split())


def _parse_dt(value):
    raw = str(value or "").strip()
    if not raw:
        return None

    try:
        dt_value = parsedate_to_datetime(raw)
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=UTC)
        return dt_value.astimezone(UTC)
    except Exception:
        pass

    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except Exception:
            continue

    if raw.endswith("+00:00"):
        try:
            return datetime.strptime(raw[:-6], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        except Exception:
            return None
    return None


def _find_first(element, names):
    for child in list(element or []):
        if _local(child.tag) in names:
            return child
    return None


def _all_children(element, name):
    return [child for child in list(element or []) if _local(child.tag) == name]


def _atom_link(entry):
    for link in _all_children(entry, "link"):
        href = (link.attrib.get("href") or "").strip()
        rel = (link.attrib.get("rel") or "").strip().lower()
        if href and rel in ("", "alternate"):
            return href
    for link in _all_children(entry, "link"):
        href = (link.attrib.get("href") or "").strip()
        if href:
            return href
    return ""


def parse_feed(xml_text):
    """Parse RSS or Atom payload into normalized entries."""

    payload = (xml_text or "").strip()
    if not payload:
        return {"title": "", "entries": [], "parse_error": "empty_payload"}

    try:
        root = ET.fromstring(payload)
    except Exception as exc:
        return {"title": "", "entries": [], "parse_error": "xml_parse_error: {0}".format(exc)}

    root_name = _local(root.tag).lower()
    if root_name == "feed":
        title = _strip_html(_text(_find_first(root, ("title",))))
        entries = []
        for entry in _all_children(root, "entry"):
            categories = []
            for category in _all_children(entry, "category"):
                term = (category.attrib.get("term") or "").strip()
                categories.append(term or _strip_html(_text(category)))
            entries.append(
                {
                    "title": _strip_html(_text(_find_first(entry, ("title",)))),
                    "url": _atom_link(entry) or _strip_html(_text(_find_first(entry, ("id",)))),
                    "published_at": _parse_dt(_text(_find_first(entry, ("published", "updated")))),
                    "summary": _strip_html(_text(_find_first(entry, ("summary",)))),
                    "content": _strip_html(_text(_find_first(entry, ("content",)))),
                    "categories": [item for item in categories if item],
                }
            )
        return {"title": title, "entries": entries, "parse_error": None}

    channel = _find_first(root, ("channel",)) or root
    title = _strip_html(_text(_find_first(channel, ("title",))))
    entries = []
    for item in channel.iter():
        if _local(item.tag) != "item":
            continue
        content_node = None
        for child in list(item):
            if _local(child.tag) in ("encoded", "content"):
                content_node = child
                break
        categories = [_strip_html(_text(category)) for category in _all_children(item, "category")]
        url = _strip_html(_text(_find_first(item, ("link",))))
        if not url:
            url = _strip_html(_text(_find_first(item, ("guid",))))
        entries.append(
            {
                "title": _strip_html(_text(_find_first(item, ("title",)))),
                "url": url,
                "published_at": _parse_dt(_text(_find_first(item, ("pubDate", "date", "published", "updated")))),
                "summary": _strip_html(_text(_find_first(item, ("description", "summary")))),
                "content": _strip_html(_text(content_node)),
                "categories": [item for item in categories if item],
            }
        )
    return {"title": title, "entries": entries, "parse_error": None}


def _source_label(feed_url, feed_title):
    try:
        host = (urlparse(feed_url).hostname or "").strip().lower()
    except Exception:
        host = ""
    return host or (feed_title or "rss").strip() or "rss"


def _dedup_hash(source, url, title, published_at):
    payload = "|".join(
        [
            str(source or "").strip(),
            str(url or "").strip(),
            published_at.astimezone(UTC).isoformat(),
            str(title or "").strip(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _default_fetch_text(feed_url, timeout_s, proxy=""):
    import requests

    kwargs = {"timeout": float(timeout_s)}
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    response = requests.get(feed_url, **kwargs)
    response.raise_for_status()
    return response.text


@register_fetcher("rss", "news")
class RssNewsFetcher(BaseFetcher):
    """Minimal RSS/Atom news fetcher."""

    def __init__(self, config=None, fetch_text=None, now_provider=None):
        self._config = config or load_config()
        self._fetch_text = fetch_text or _default_fetch_text
        self._now_provider = now_provider or (lambda: datetime.now(tz=UTC))

    def transform_query(self, params):
        feeds = _parse_feeds(params.get("feeds") or getattr(self._config.news, "feeds", []))
        return NewsQuery(
            feeds=feeds,
            limit=params.get("limit") or getattr(self._config.news, "limit", 100),
            window_hours=params.get("window_hours") or getattr(self._config.news, "window_hours", 72),
            timeout_s=params.get("timeout_s") or getattr(self._config.news, "timeout_seconds", 20),
        )

    async def extract(self, query):
        cutoff = self._now_provider() - timedelta(hours=query.window_hours)
        proxy = getattr(getattr(self._config, "runtime", object()), "http_proxy", "") or ""
        rows = []
        for feed_url in query.feeds:
            try:
                xml_text = self._fetch_text(feed_url, query.timeout_s, proxy=proxy)
            except TypeError:
                xml_text = self._fetch_text(feed_url, query.timeout_s, proxy)
            except Exception as exc:
                logger.warning("rss fetch failed feed=%s error=%s", feed_url, exc)
                continue

            parsed = parse_feed(xml_text)
            source = _source_label(feed_url, parsed.get("title"))
            for entry in parsed.get("entries", []):
                published_at = entry.get("published_at")
                if not isinstance(published_at, datetime):
                    continue
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
                else:
                    published_at = published_at.astimezone(UTC)
                if published_at < cutoff:
                    continue
                normalized = dict(entry)
                normalized["published_at"] = published_at
                normalized["source"] = source
                rows.append(normalized)

        rows.sort(key=lambda row: row.get("published_at") or datetime(1970, 1, 1, tzinfo=UTC), reverse=True)
        if query.limit:
            rows = rows[: query.limit]
        return rows

    def transform_data(self, raw):
        articles = []
        for entry in list(raw or []):
            published_at = entry.get("published_at")
            if not isinstance(published_at, datetime):
                continue
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            else:
                published_at = published_at.astimezone(UTC)

            title = str(entry.get("title") or entry.get("summary") or "").strip()
            if not title:
                continue
            summary = str(entry.get("summary") or title).strip()
            source = str(entry.get("source") or "rss").strip() or "rss"
            url = str(entry.get("url") or "").strip()
            articles.append(
                {
                    "dedup_hash": _dedup_hash(source, url, title, published_at),
                    "source": source,
                    "url": url,
                    "published_at": published_at,
                    "title": title,
                    "summary": summary,
                    "content": str(entry.get("content") or summary).strip(),
                    "symbols": list(entry.get("symbols") or []),
                    "categories": list(entry.get("categories") or []),
                    "language": str(entry.get("language") or "en"),
                }
            )
        return articles


class RssNewsCollector(object):
    """Minimal RSS news collector with storage integration."""

    def __init__(self, config=None, writer=None, batch_start=None, fetcher=None, fetch_text=None):
        self._config = config or load_config()
        self._writer = writer or TimescaleNewsWriter()
        self._batch_start = batch_start or batch_module.start_batch
        self._fetcher = fetcher
        self._fetch_text = fetch_text
        self._runtime_fetcher = None
        self._owns_writer = writer is None

    def _fetcher_instance(self):
        if self._fetcher is not None:
            return self._fetcher
        if self._runtime_fetcher is not None:
            return self._runtime_fetcher
        fetcher_cls = ProviderRegistry.get("rss", "news")
        if fetcher_cls is None:
            fetcher_cls = RssNewsFetcher
        if fetcher_cls is None:
            raise ValueError("Provider not registered: rss")
        self._runtime_fetcher = fetcher_cls(config=self._config, fetch_text=self._fetch_text)
        return self._runtime_fetcher

    def collect(self, feeds=None):
        fetcher = self._fetcher_instance()
        return fetcher.fetch_sync(
            feeds=feeds or getattr(self._config.news, "feeds", []),
            limit=getattr(self._config.news, "limit", 100),
            window_hours=getattr(self._config.news, "window_hours", 72),
            timeout_s=getattr(self._config.news, "timeout_seconds", 20),
        )

    def save(self, articles):
        if not articles:
            return 0
        batch_id = self._batch_start(source="rss_news", data_type="news_articles", market="news")
        return self._writer.insert_articles(articles, ingest_batch_id=batch_id)

    def run_once(self, feeds=None):
        if not getattr(self._config.news, "enabled", False):
            logger.info("news collector disabled by config")
            return 0
        return self.save(self.collect(feeds=feeds))

    def close(self):
        if self._owns_writer and hasattr(self._writer, "close"):
            self._writer.close()
