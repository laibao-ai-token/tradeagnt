"""News page module — RSS polling, news display, and news TUI rendering."""

from __future__ import annotations
import concurrent.futures

import concurrent.futures
from pathlib import Path

import curses
import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from tradecat.common.utils.scheduler import wait_seconds
from tradecat.tui.db import SignalRow, fetch_recent, parse_ts, probe

# Re-export from parent for compatibility
from tradecat.tui.news_db import (
    StoredNewsArticle,
    fetch_recent_news_articles,
    resolve_news_database_schema,
    resolve_news_database_url,
)
from tradecat.tui.news_defaults import (
    CORE_GROUP,
    PRIMARY_TIER,
    SUPPLEMENTAL_TIER,
    UNKNOWN_GROUP,
    UNKNOWN_TIER,
    default_tui_news_rss_feeds_value,
    extract_source_meta_tags,
    news_source_code,
    news_source_group,
    news_source_tier,
)
from tradecat.tui.news_events import NewsEvent, cluster_news_items
from tradecat.tui.news_health import (
    NewsHealthSnapshot,
    build_live_news_health,
    load_news_collector_health,
    resolve_news_health_log_path,
)


def _safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    """Safe wrapper for curses addstr that handles boundary errors."""
    try:
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x < 0:
            return
        available = max_x - x
        if available <= 0:
            return
        win.addnstr(y, x, s, available, attr)
    except curses.error:
        pass


def _truncate(s: str, width: int) -> str:
    """Truncate string to fit within display width."""
    if width <= 0:
        return ""
    result = []
    current_width = 0
    for ch in s:
        ch_width = 2 if ord(ch) > 0x7F else 1
        if current_width + ch_width > width:
            break
        result.append(ch)
        current_width += ch_width
    return "".join(result)


def _char_display_width(ch: str) -> int:
    """Return display width of a character."""
    if len(ch) != 1:
        return 0
    cp = ord(ch)
    if cp <= 0x7F:
        return 1
    # CJK range
    if (0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F or
            0xFF00 <= cp <= 0xFFEF or 0x3400 <= cp <= 0x4DBF):
        return 2
    return 1


def _text_display_width(text: str) -> int:
    """Return display width of text."""
    return sum(_char_display_width(ch) for ch in text)


# News source filter constants
_NEWS_SOURCE_FILTER_ALL = "全部"
_DIRECT_NEWS_PREFIX = "direct:"

# Missing constants from tui.py
_REPO_ROOT = Path(__file__).resolve().parents[4]
_NEWS_CATEGORIES = ("全部", "宏观", "公司", "加密", "政策")
_NEWS_SOURCE_FILTER_PRIMARY = "主链"
_NEWS_SOURCE_FILTER_SUPPLEMENTAL = "补充"
_NEWS_WINDOWS_H = (1, 6, 24)
_RSS_TAG_RE = re.compile(r"<[^>]+>")

# Import shared helpers from tui.py
from tradecat.tui._helpers import _display_name, _draw_box, _safe_hline, _safe_vline, _char_display_width, _text_display_width, _truncate


# === NewsItem ===

class NewsItem:
    id: str
    published_at: float
    source: str
    category: str
    severity: str
    symbols: tuple[str, ...]
    source_group: str = ""
    source_tier: str = ""
    title: str = ""
    summary: str = ""
    url: str = ""
    direction: str = "Neutral"
    confidence: float = 0.50
    impact_assets: tuple[str, ...] = ()
    suggestion: str = ""



# === NewsPageState ===

class NewsPageState:
    focus: str = "middle"  # middle / right
    watch_selected: int = 0
    news_selected: int = 0
    news_scroll: int = 0
    category_idx: int = 0
    source_idx: int = 0
    window_idx: int = 2
    search_query: str = ""
    watch_filter_locked: bool = False



# === NewsFeedSnapshot ===

class NewsFeedSnapshot:
    mode: str  # DB / RSS / LIVE / MIX
    items: tuple[NewsItem, ...] = ()
    feeds: tuple[str, ...] = ()
    last_ok_at: float = 0.0
    latest_item_at: float = 0.0
    refresh_s: float = 0.0
    last_error: str = ""
    health: NewsHealthSnapshot = field(default_factory=NewsHealthSnapshot)



# === RSS+RssNewsPoller ===

def _rss_local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _rss_text(el) -> str:
    if el is None:
        return ""
    return (getattr(el, "text", "") or "").strip()


def _rss_strip_html(raw: str) -> str:
    if not raw:
        return ""
    raw = html.unescape(raw)
    raw = _RSS_TAG_RE.sub(" ", raw)
    return " ".join(raw.split())


def _rss_parse_dt(raw: str) -> float | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return float(dt.timestamp())
    except Exception:
        pass
    # Atom often uses RFC3339/ISO8601 (e.g. 2026-03-05T12:34:56Z)
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return float(dt.timestamp())
    except Exception:
        return None


def _rss_find_first(el, names: tuple[str, ...]):
    for child in list(el):
        if _rss_local(getattr(child, "tag", "")) in names:
            return child
    return None


def _rss_all_children(el, name: str):
    out = []
    for child in list(el):
        if _rss_local(getattr(child, "tag", "")) == name:
            out.append(child)
    return out


def _rss_atom_link(entry) -> str:
    for link in _rss_all_children(entry, "link"):
        rel = (getattr(link, "attrib", {}) or {}).get("rel", "")
        href = (getattr(link, "attrib", {}) or {}).get("href", "")
        rel = (rel or "").strip().lower()
        href = (href or "").strip()
        if not href:
            continue
        if rel in ("", "alternate"):
            return href
    for link in _rss_all_children(entry, "link"):
        href = (getattr(link, "attrib", {}) or {}).get("href", "")
        href = (href or "").strip()
        if href:
            return href
    return ""


def _parse_rss_feed(xml_text: str) -> tuple[str, list[dict[str, object]]]:
    """
    Parse RSS/Atom XML text (best-effort, stdlib only).
    Returns: (feed_title, entries) where entry has: title/url/published_at/summary/categories.
    """
    xml_text = (xml_text or "").strip()
    if not xml_text:
        return "", []

    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
    except Exception:
        return "", []

    root_name = _rss_local(getattr(root, "tag", "")).lower()

    if root_name == "feed":  # Atom
        feed_title = _rss_strip_html(_rss_text(_rss_find_first(root, ("title",))))
        entries: list[dict[str, object]] = []
        for entry in _rss_all_children(root, "entry"):
            title = _rss_strip_html(_rss_text(_rss_find_first(entry, ("title",))))
            url = _rss_atom_link(entry) or _rss_strip_html(_rss_text(_rss_find_first(entry, ("id",))))
            summary = _rss_strip_html(_rss_text(_rss_find_first(entry, ("summary",))))
            content = _rss_strip_html(_rss_text(_rss_find_first(entry, ("content",))))
            published = _rss_text(_rss_find_first(entry, ("published", "updated")))
            published_at = _rss_parse_dt(published)
            categories: list[str] = []
            for cat in _rss_all_children(entry, "category"):
                term = (getattr(cat, "attrib", {}) or {}).get("term", "")
                term = (term or "").strip()
                if term:
                    categories.append(term)
                else:
                    categories.append(_rss_strip_html(_rss_text(cat)))
            entries.append(
                {
                    "title": title,
                    "url": url,
                    "published_at": published_at,
                    "summary": summary or content,
                    "categories": [c for c in categories if c],
                }
            )
        return feed_title, entries

    # RSS 2.0: <rss><channel>...<item>...</item></channel></rss>
    channel = _rss_find_first(root, ("channel",)) or root
    feed_title = _rss_strip_html(_rss_text(_rss_find_first(channel, ("title",))))
    entries = []
    for item in channel.iter():
        if _rss_local(getattr(item, "tag", "")) != "item":
            continue
        title = _rss_strip_html(_rss_text(_rss_find_first(item, ("title",))))
        url = _rss_strip_html(_rss_text(_rss_find_first(item, ("link",))))
        if not url:
            url = _rss_strip_html(_rss_text(_rss_find_first(item, ("guid",))))
        pub = _rss_text(_rss_find_first(item, ("pubDate", "date", "published", "updated")))
        published_at = _rss_parse_dt(pub)
        summary = _rss_strip_html(_rss_text(_rss_find_first(item, ("description", "summary"))))
        categories = [_rss_strip_html(_rss_text(c)) for c in _rss_all_children(item, "category")]
        entries.append(
            {
                "title": title,
                "url": url,
                "published_at": published_at,
                "summary": summary,
                "categories": [c for c in categories if c],
            }
        )
    return feed_title, entries


_DIRECT_NEWS_PREFIX = "direct://"


def _parse_rss_feeds_value(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    for piece in raw.replace("\n", ",").split(","):
        piece = piece.strip()
        if piece:
            parts.append(piece)
    out: list[str] = []
    for u in parts:
        normalized = u.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered.startswith(_DIRECT_NEWS_PREFIX):
            out.append(lowered)
            continue
        if normalized.startswith("file://"):
            out.append(normalized)
            continue
        if normalized.startswith("http://") or normalized.startswith("https://"):
            out.append(normalized)
            continue
        if normalized.startswith("//"):
            out.append(f"https:{normalized}")
            continue
        # Friendly fallback: allow "rsshub.app/jin10" (no scheme) in env/config.
        if re.match(r"^[A-Za-z0-9.-]+/.+", normalized) and "." in normalized.split("/", 1)[0]:
            out.append(f"https://{normalized}")
            continue
        local_path = Path(normalized).expanduser()
        if not local_path.is_absolute():
            local_path = (_REPO_ROOT / local_path).resolve()
        if local_path.exists():
            out.append(local_path.as_uri())
    return out


def _split_direct_news_source(source: str) -> str:
    value = (source or "").strip().lower()
    if value.startswith(_DIRECT_NEWS_PREFIX):
        return value[len(_DIRECT_NEWS_PREFIX) :].strip().strip("/")
    return value


def _is_direct_news_source(source: str) -> bool:
    return (source or "").strip().lower().startswith(_DIRECT_NEWS_PREFIX)


def _news_source_mode(feeds: tuple[str, ...]) -> str:
    count = len(feeds)
    has_direct = any(_is_direct_news_source(feed) for feed in feeds)
    has_rss = any(not _is_direct_news_source(feed) for feed in feeds)
    if has_direct and has_rss:
        return f"MIX({count})"
    if has_direct:
        return f"LIVE({count})"
    return "RSS"


def _news_source_code(feed_url: str, feed_title: str) -> str:
    if "demo.tradecat.local" in (feed_url or "").strip().lower() or (feed_url or "").startswith("file://"):
        return "DEMO"
    code = news_source_code(feed_url, feed_title)
    if code:
        return code
    title = (feed_title or "").strip()
    if title:
        return _truncate(title, 4)
    return "RSS"


def _news_normalize_text(value: object) -> str:
    return _rss_strip_html(str(value or "").strip())


def _news_parse_timestamp(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        return ts if ts > 0 else None
    raw = str(value).strip()
    if not raw:
        return None
    if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        try:
            return _news_parse_timestamp(float(raw))
        except Exception:
            return None
    return _rss_parse_dt(raw)


def _news_with_default_tz(value: object, tz_suffix: str = "+08:00") -> object:
    raw = str(value or "").strip()
    if not raw:
        return value
    if re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", raw):
        return raw
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$", raw):
        return f"{raw}{tz_suffix}"
    return value


def _news_symbol_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    for item in value:
        candidate = ""
        if isinstance(item, dict):
            for key in ("symbol", "code", "stockCode", "stock_code", "secuCode", "secu_code", "ticker", "name"):
                candidate = str(item.get(key) or "").strip()
                if candidate:
                    break
        else:
            candidate = str(item or "").strip()
        if not candidate:
            continue
        candidate = candidate.upper()
        if candidate not in out:
            out.append(candidate)
    return tuple(out[:8])


def _news_http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, object] | None = None,
    timeout_s: float = 10.0,
    allow_jsonp: bool = False,
) -> object:
    if params:
        query = urllib.parse.urlencode([(str(k), str(v)) for k, v in params.items()], doseq=True)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{query}"
    req_headers = {"User-Agent": "TradeCatTUI/news"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read()
    raw = body.decode("utf-8", errors="ignore").lstrip("\ufeff").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if not allow_jsonp:
            raise
        start = raw.find("(")
        end = raw.rfind(")")
        if start >= 0 and end > start:
            return json.loads(raw[start + 1 : end].strip())
        raise


def _news_http_get_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, object] | None = None,
    timeout_s: float = 10.0,
) -> str:
    if params:
        query = urllib.parse.urlencode([(str(k), str(v)) for k, v in params.items()], doseq=True)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{query}"
    req_headers = {"User-Agent": "TradeCatTUI/news"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read()
    return body.decode("utf-8", errors="ignore")


def _direct_news_entry(
    *,
    title: object,
    summary: object,
    url: object,
    published_at: object,
    categories: list[str] | None = None,
    severity: str = "",
    symbols: tuple[str, ...] = (),
) -> dict[str, object] | None:
    title_text = _news_normalize_text(title)
    summary_text = _news_normalize_text(summary)
    if not title_text:
        title_text = summary_text
    if not title_text:
        return None
    ts = _news_parse_timestamp(published_at)
    if ts is None:
        return None
    return {
        "title": title_text,
        "summary": summary_text or title_text,
        "url": str(url or "").strip(),
        "published_at": ts,
        "categories": [str(cat).strip() for cat in (categories or []) if str(cat).strip()],
        "severity": str(severity or "").strip().upper(),
        "symbols": symbols,
    }


def _fetch_direct_news_entries(source: str, timeout_s: float) -> list[dict[str, object]]:
    target = _split_direct_news_source(source)
    if target == "jin10":
        payload = _news_http_get_json(
            "https://flash-api.jin10.com/get_flash_list",
            headers={"x-app-id": "bVBF4FyRTn5NJF5n", "x-version": "1.0.0"},
            params={"channel": "-8200", "vip": "1"},
            timeout_s=timeout_s,
        )
        rows = payload.get("data") if isinstance(payload, dict) else []
        entries: list[dict[str, object]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or int(row.get("type") or 0) == 1:
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            content = _news_normalize_text(data.get("content") if isinstance(data, dict) else "")
            title = _news_normalize_text(data.get("title") if isinstance(data, dict) else "")
            if not title and content:
                matched = re.match(r"^【([^】]+)】\s*(.*)$", content)
                if matched:
                    title = matched.group(1).strip()
                    content = matched.group(2).strip() or content
                else:
                    title = content
            entry = _direct_news_entry(
                title=title,
                summary=content,
                url=(data.get("source_link") if isinstance(data, dict) else "") or "https://www.jin10.com/",
                published_at=_news_with_default_tz(row.get("time") if isinstance(row, dict) else None),
                categories=[
                    _news_normalize_text(tag.get("name"))
                    for tag in (row.get("tags") if isinstance(row.get("tags"), list) else [])
                    if isinstance(tag, dict)
                ],
                severity="HIGH" if int(row.get("important") or 0) > 0 else "",
            )
            if entry is not None:
                entries.append(entry)
        return entries

    if target == "gelonghui/live":
        payload = _news_http_get_json(
            "https://www.gelonghui.com/api/live-channels/all/lives/v4",
            timeout_s=timeout_s,
        )
        rows = payload.get("result") if isinstance(payload, dict) else []
        entries = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            source_info = row.get("source") if isinstance(row.get("source"), dict) else {}
            categories = [
                _news_normalize_text(source_info.get("name") if isinstance(source_info, dict) else ""),
                _news_normalize_text(row.get("contentPrefix")),
            ]
            entry = _direct_news_entry(
                title=row.get("title") or row.get("content"),
                summary=row.get("content") or row.get("title"),
                url=row.get("route") or "https://www.gelonghui.com/live",
                published_at=row.get("createTimestamp"),
                categories=categories,
                severity="HIGH" if int(row.get("level") or 0) >= 2 else "",
                symbols=_news_symbol_list(row.get("relatedStocks")),
            )
            if entry is not None:
                entries.append(entry)
        return entries

    if target == "10jqka/realtimenews":
        payload = _news_http_get_json(
            "https://news.10jqka.com.cn/tapp/news/push/stock",
            params={"page": "1", "tag": ""},
            timeout_s=timeout_s,
        )
        data = payload.get("data") if isinstance(payload, dict) else {}
        rows = data.get("list") if isinstance(data, dict) else []
        entries = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            categories = []
            for tag in (row.get("tags") if isinstance(row.get("tags"), list) else []):
                if isinstance(tag, dict):
                    categories.append(_news_normalize_text(tag.get("name")))
            for tag in (row.get("tagInfo") if isinstance(row.get("tagInfo"), list) else []):
                if isinstance(tag, dict):
                    categories.append(_news_normalize_text(tag.get("name")))
            entry = _direct_news_entry(
                title=row.get("title") or row.get("digest"),
                summary=row.get("short") or row.get("digest") or row.get("title"),
                url=row.get("url") or row.get("shareUrl") or "https://news.10jqka.com.cn/realtimenews.html",
                published_at=row.get("ctime") or row.get("rtime"),
                categories=categories,
                severity="HIGH" if str(row.get("color") or "") == "2" else "",
                symbols=_news_symbol_list(row.get("stock")),
            )
            if entry is not None:
                entries.append(entry)
        return entries

    if target == "sina/7x24":
        payload = _news_http_get_json(
            "https://zhibo.sina.com.cn/api/zhibo/feed",
            params={"zhibo_id": "152", "page": "1", "pagesize": "50", "tag_id": "0", "dire": "f"},
            timeout_s=timeout_s,
        )
        data = payload.get("result") if isinstance(payload, dict) else {}
        feed = data.get("data") if isinstance(data, dict) else {}
        feed_info = feed.get("feed") if isinstance(feed, dict) else {}
        rows = feed_info.get("list") if isinstance(feed_info, dict) else []
        entries = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            ext_raw = row.get("ext")
            ext: dict[str, object] = {}
            if isinstance(ext_raw, str) and ext_raw.strip():
                try:
                    parsed_ext = json.loads(ext_raw)
                    if isinstance(parsed_ext, dict):
                        ext = parsed_ext
                except Exception:
                    ext = {}
            categories = [
                _news_normalize_text(tag.get("name"))
                for tag in (row.get("tag") if isinstance(row.get("tag"), list) else [])
                if isinstance(tag, dict)
            ]
            entry = _direct_news_entry(
                title=row.get("rich_text"),
                summary=row.get("rich_text"),
                url=row.get("docurl") or ext.get("docurl") or "https://finance.sina.com.cn/7x24/notification.shtml",
                published_at=_news_with_default_tz(row.get("create_time")),
                categories=categories,
                severity="HIGH" if int(row.get("is_focus") or 0) > 0 else "",
                symbols=_news_symbol_list(ext.get("stocks")),
            )
            if entry is not None:
                entries.append(entry)
        return entries

    if target == "eastmoney/kuaixun":
        payload = _news_http_get_json(
            "http://newsapi.eastmoney.com/kuaixun/v2/api/list",
            params={"column": "102", "p": "1", "limit": "50", "callback": "cb"},
            timeout_s=timeout_s,
            allow_jsonp=True,
        )
        rows = payload.get("news") if isinstance(payload, dict) else []
        entries = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            categories = [_news_normalize_text(row.get("Art_Media_Name"))]
            entry = _direct_news_entry(
                title=row.get("title") or row.get("digest"),
                summary=row.get("digest") or row.get("title"),
                url=row.get("url_m") or row.get("url_w") or "https://kuaixun.eastmoney.com/7_24.html",
                published_at=_news_with_default_tz(row.get("showtime") or row.get("ordertime")),
                categories=categories,
            )
            if entry is not None:
                entries.append(entry)
        return entries

    if target == "cls/telegraph":
        raw = _news_http_get_text("https://www.cls.cn/telegraph", timeout_s=timeout_s)
        matched = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw, re.S)
        if not matched:
            return []
        payload = json.loads(matched.group(1))
        props = payload.get("props") if isinstance(payload, dict) else {}
        state = {}
        if isinstance(props, dict):
            state = props.get("initialState") if isinstance(props.get("initialState"), dict) else {}
            if not state:
                page_props = props.get("pageProps") if isinstance(props.get("pageProps"), dict) else {}
                state = page_props.get("initialState") if isinstance(page_props.get("initialState"), dict) else {}
        telegraph = state.get("telegraph") if isinstance(state, dict) else {}
        rows = telegraph.get("telegraphList") if isinstance(telegraph, dict) else []
        entries = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            categories = []
            for subject in (row.get("subjects") if isinstance(row.get("subjects"), list) else []):
                if isinstance(subject, dict):
                    categories.append(_news_normalize_text(subject.get("subject_name")))
            entry = _direct_news_entry(
                title=row.get("title") or row.get("content"),
                summary=row.get("brief") or row.get("content") or row.get("title"),
                url=row.get("shareurl") or "https://www.cls.cn/telegraph",
                published_at=row.get("ctime") or row.get("modified_time"),
                categories=categories,
                severity="HIGH" if str(row.get("level") or "").upper() in {"A", "B"} else "",
                symbols=_news_symbol_list(row.get("stock_list")),
            )
            if entry is not None:
                entries.append(entry)
        return entries

    if target == "wallstreetcn/live":
        payload = _news_http_get_json(
            "https://api-one.wallstcn.com/apiv1/content/lives",
            params={"channel": "global-channel", "limit": "100"},
            timeout_s=timeout_s,
        )
        data = payload.get("data") if isinstance(payload, dict) else {}
        rows = data.get("items") if isinstance(data, dict) else []
        entries = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            categories = [_news_normalize_text(row.get("global_channel_name"))]
            categories.extend(
                _news_normalize_text(tag)
                for tag in (row.get("channels") if isinstance(row.get("channels"), list) else [])
                if isinstance(tag, str)
            )
            entry = _direct_news_entry(
                title=row.get("title") or row.get("content_text"),
                summary=row.get("content_text") or row.get("title"),
                url=row.get("uri") or "https://wallstreetcn.com/live",
                published_at=row.get("display_time"),
                categories=categories,
                severity="HIGH" if int(row.get("score") or 0) >= 2 else "",
                symbols=_news_symbol_list(row.get("symbols")),
            )
            if entry is not None:
                entries.append(entry)
        return entries

    if target == "eeo/kuaixun":
        payload = _news_http_get_json(
            "https://app.eeo.com.cn/",
            params={
                "app": "article",
                "controller": "index",
                "action": "getMoreArticle",
                "catid": "3690",
                "uuid": "b048c7211db949eeb7443cd5b9b3bfe3",
                "page": "1",
                "pageSize": "50",
            },
            timeout_s=timeout_s,
        )
        rows = payload.get("data") if isinstance(payload, dict) else []
        entries = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            entry = _direct_news_entry(
                title=row.get("title") or row.get("description"),
                summary=row.get("description") or row.get("content") or row.get("title"),
                url=row.get("url") or "https://www.eeo.com.cn/kuaixun/",
                published_at=_news_with_default_tz(row.get("published")),
                categories=[_news_normalize_text(row.get("catname"))],
            )
            if entry is not None:
                entries.append(entry)
        return entries

    raise ValueError(f"unsupported direct news source: {source}")


def _infer_news_category(categories: list[str], title: str) -> str:
    cat_blob = " ".join([c for c in categories if c]).lower()
    t = (title or "").lower()
    blob = f"{cat_blob} {t}"

    crypto_keys = ("crypto", "btc", "eth", "比特币", "以太坊", "数字货币", "加密")
    if any(k in blob for k in crypto_keys):
        return "加密"
    policy_keys = ("fed", "ecb", "bis", "央行", "美联储", "加息", "降息", "利率", "政策", "监管")
    if any(k in blob for k in policy_keys):
        return "政策"
    company_keys = ("earnings", "guidance", "sec", "filing", "财报", "公司", "公告")
    if any(k in blob for k in company_keys):
        return "公司"
    return "宏观"


def _infer_news_severity(title: str, summary: str) -> str:
    blob = f"{title} {summary}".lower()
    high_keys = ("突发", "breaking", "emergency", "紧急", "爆炸", "崩盘")
    if any(k in blob for k in high_keys):
        return "HIGH"
    return "MID"


def _news_dedup_id(source: str, url: str, title: str, published_at: float) -> str:
    key = (url or "").strip()
    if not key:
        key = f"{source}|{int(published_at)}|{title}".strip()
    digest = hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()
    return f"rss-{digest[:16]}"


def _news_item_from_stored_article(article: StoredNewsArticle) -> NewsItem:
    source = _news_source_code(article.url or article.source, article.source)
    summary = article.summary.strip() or article.title.strip()
    clean_categories = tuple(
        str(item).strip() for item in article.categories if str(item).strip() and not str(item).strip().lower().startswith("tc_source_")
    )
    source_group, source_tier = extract_source_meta_tags(article.categories)
    if source_group == UNKNOWN_GROUP:
        source_group = news_source_group(article.url or article.source, source)
    if source_tier == UNKNOWN_TIER:
        source_tier = news_source_tier(article.url or article.source, source)
    category = _infer_news_category(list(clean_categories), article.title)
    severity = _infer_news_severity(article.title, summary)
    symbols = tuple(article.symbols)
    item_id = article.dedup_hash.strip() or _news_dedup_id(source, article.url, article.title, article.published_at)
    return NewsItem(
        id=item_id,
        published_at=float(article.published_at),
        source=source,
        category=category,
        severity=severity,
        symbols=symbols,
        source_group=source_group,
        source_tier=source_tier,
        title=article.title.strip(),
        summary=summary,
        url=article.url.strip() or article.source.strip(),
        direction="Neutral",
        confidence=0.50,
        impact_assets=symbols,
        suggestion="",
    )


class RssNewsPoller:
    """Poll the unified news chain for the TUI.

    Preferred path: read the configured `<schema>.news_articles` table from the database.
    Fallback path: fetch the configured direct/RSS feeds locally when the DB is
    unavailable or still empty.
    """

    def __init__(
        self,
        feeds: list[str],
        *,
        refresh_s: float = 2.0,
        timeout_s: float = 5.0,
        max_items: int = 300,
        database_url: str = "",
        database_schema: str = "alternative",
        database_window_h: int = 72,
        database_timeout_s: float = 5.0,
        database_stale_after_s: float = 60.0,
    ) -> None:
        self._feeds = tuple(_parse_rss_feeds_value(",".join(feeds)))
        self._mode = _news_source_mode(self._feeds)
        self._refresh_s = max(2.0, float(refresh_s))
        self._timeout_s = max(1.0, float(timeout_s))
        self._max_items = max(50, int(max_items))
        self._database_url = str(database_url or "").strip()
        self._database_schema = str(database_schema or "alternative").strip() or "alternative"
        self._database_window_h = max(1, int(database_window_h))
        self._database_timeout_s = max(1.0, float(database_timeout_s))
        self._database_stale_after_s = max(15.0, float(database_stale_after_s))
        self._collector_health_log = resolve_news_health_log_path(_REPO_ROOT)
        self._lock = threading.Lock()
        self._items: list[NewsItem] = []
        self._last_error = ""
        self._last_ok_at = 0.0
        self._latest_item_at = 0.0
        self._health = NewsHealthSnapshot()
        self._backend = "DB" if self._database_url else (self._mode or "RSS")
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._wake = threading.Event()
        self._t = threading.Thread(target=self._run, name="news-poller", daemon=True)

    def start(self) -> None:
        if not self._database_url and not self._feeds:
            return
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        try:
            self._t.join(timeout=1.0)
        except Exception:
            pass

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
            self._wake.set()

    def request_refresh(self) -> None:
        self._wake.set()

    def snapshot(self) -> NewsFeedSnapshot:
        with self._lock:
            mode = "DB" if self._backend == "DB" else self._mode
            return NewsFeedSnapshot(
                mode=mode,
                items=tuple(self._items),
                feeds=tuple(self._feeds),
                last_ok_at=float(self._last_ok_at),
                latest_item_at=float(self._latest_item_at),
                refresh_s=float(self._refresh_s),
                last_error=str(self._last_error or ""),
                health=self._health,
            )

    def _fetch_one_feed(self, feed_url: str, headers: dict[str, str], started: float) -> list[NewsItem]:
        if _is_direct_news_source(feed_url):
            feed_title = ""
            entries = _fetch_direct_news_entries(feed_url, timeout_s=self._timeout_s)
        else:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                body = resp.read()
            text = body.decode("utf-8", errors="ignore")
            feed_title, entries = _parse_rss_feed(text)

        source = _news_source_code(feed_url, feed_title)
        source_group = news_source_group(feed_url, source)
        source_tier = news_source_tier(feed_url, source)
        is_demo_feed = feed_url.startswith("file://")
        items: list[NewsItem] = []
        for idx, entry in enumerate(entries):
            title = _news_normalize_text(entry.get("title"))
            if not title:
                continue
            url = str(entry.get("url") or "").strip()
            published_at = entry.get("published_at")
            ts = float(published_at) if isinstance(published_at, (int, float)) and float(published_at) > 0 else started
            if is_demo_feed and (ts > started or started - ts > 24 * 3600):
                ts = started - idx * 900
            summary = _news_normalize_text(entry.get("summary"))
            cats = entry.get("categories") or []
            categories = [str(c).strip() for c in cats] if isinstance(cats, list) else []
            category = _infer_news_category(categories, title)
            severity = str(entry.get("severity") or "").strip().upper() or _infer_news_severity(title, summary)
            symbols = _news_symbol_list(entry.get("symbols"))
            items.append(
                NewsItem(
                    id=_news_dedup_id(source, url, title, ts),
                    published_at=ts,
                    source=source,
                    category=category,
                    severity=severity,
                    symbols=symbols,
                    source_group=source_group,
                    source_tier=source_tier,
                    title=title,
                    summary=summary,
                    url=url or feed_url,
                    direction="Neutral",
                    confidence=0.50,
                    impact_assets=symbols,
                    suggestion="",
                )
            )
        return items

    def _fetch_live_items(self, started: float, headers: dict[str, str]) -> tuple[list[NewsItem], list[str]]:
        if not self._feeds:
            return [], []

        new_items: list[NewsItem] = []
        errors: list[str] = []
        max_workers = min(max(1, len(self._feeds)), 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="news-feed") as executor:
            futures = {
                executor.submit(self._fetch_one_feed, feed_url, headers, started): feed_url
                for feed_url in self._feeds
            }
            for future in concurrent.futures.as_completed(futures):
                feed_url = futures[future]
                try:
                    new_items.extend(future.result())
                except Exception as exc:
                    errors.append(f"{_news_source_code(feed_url, '')}: {type(exc).__name__}")

        new_items.sort(key=lambda item: float(item.published_at), reverse=True)
        if len(new_items) > self._max_items:
            new_items = new_items[: self._max_items]
        return new_items, errors

    def _fetch_database_items(self) -> list[NewsItem]:
        rows = fetch_recent_news_articles(
            self._database_url,
            limit=self._max_items,
            window_hours=self._database_window_h,
            timeout_s=self._database_timeout_s,
            schema=self._database_schema,
        )
        items = [_news_item_from_stored_article(row) for row in rows]
        items.sort(key=lambda item: float(item.published_at), reverse=True)
        return items[: self._max_items]

    def _latest_item_ts(self, items: list[NewsItem]) -> float:
        return max((float(item.published_at) for item in items), default=0.0)

    def _db_stale_reason(self, latest_item_at: float, health: NewsHealthSnapshot, now_ts: float) -> str:
        if health.available and float(health.checked_at) > 0:
            health_age_s = max(0.0, float(now_ts) - float(health.checked_at))
            if health_age_s > self._database_stale_after_s:
                return f"collector stale {_news_age_text(now_ts, float(health.checked_at))}"

        if latest_item_at <= 0:
            return ""

        item_age_s = max(0.0, float(now_ts) - float(latest_item_at))
        fallback_threshold_s = max(300.0, self._database_stale_after_s * 5.0)
        if item_age_s > fallback_threshold_s:
            return f"db stale {_news_age_text(now_ts, latest_item_at)}"
        return ""

    def _refresh_once(self, *, started: float | None = None, headers: dict[str, str] | None = None) -> None:
        request_headers = dict(headers or {"User-Agent": "TradeCatTUI/rss"})
        started_at = float(started) if started is not None else time.time()
        new_items: list[NewsItem] = []
        errors: list[str] = []
        live_errors: list[str] = []
        backend = self._mode or "RSS"
        db_attempted = False
        db_success = False
        db_items: list[NewsItem] = []
        db_health = NewsHealthSnapshot()
        db_stale_reason = ""
        live_attempted = False

        if self._database_url:
            db_attempted = True
            try:
                db_items = self._fetch_database_items()
                db_success = True
                db_health = load_news_collector_health(self._collector_health_log)
                if db_items:
                    latest_db_item_at = self._latest_item_ts(db_items)
                    db_stale_reason = self._db_stale_reason(latest_db_item_at, db_health, started_at)
                    new_items = db_items
                    if not db_stale_reason:
                        backend = "DB"
                    else:
                        errors.append(db_stale_reason)
            except Exception as exc:
                errors.append(f"DB: {type(exc).__name__}")

        should_try_live = bool(self._feeds) and ((not new_items) or bool(db_stale_reason))
        if should_try_live:
            live_attempted = True
            live_items, live_errors = self._fetch_live_items(started_at, request_headers)
            if live_items:
                new_items = live_items
                backend = self._mode or "RSS"
                errors = list(live_errors)
            else:
                errors.extend(live_errors)
                if db_stale_reason and db_items:
                    new_items = db_items
                    backend = "DB"

        finished_at = time.time()
        latest_item_at = self._latest_item_ts(new_items)
        health = NewsHealthSnapshot()
        if live_attempted:
            health = build_live_news_health(len(self._feeds), live_errors, checked_at=finished_at)
        elif db_attempted:
            health = db_health
        elif self._feeds:
            health = build_live_news_health(len(self._feeds), errors, checked_at=finished_at)

        with self._lock:
            self._backend = backend if new_items else ("DB" if (db_attempted and db_success) else (self._backend or backend))
            if new_items:
                self._items = new_items
                self._last_ok_at = finished_at
                self._latest_item_at = latest_item_at
                if db_stale_reason and backend == "DB":
                    self._last_error = "; ".join(errors) if errors else db_stale_reason
                else:
                    self._last_error = ""
                if health.available:
                    self._health = health
            else:
                if health.available:
                    self._health = health
                if db_attempted and db_success:
                    self._last_ok_at = finished_at
                    if self._items:
                        self._latest_item_at = max((float(item.published_at) for item in self._items), default=0.0)
                        self._last_error = db_stale_reason or ""
                    else:
                        self._latest_item_at = 0.0
                        self._last_error = db_stale_reason or "waiting for collector"
                else:
                    self._last_error = "; ".join(errors) if errors else (self._last_error or "no data")

    def _run(self) -> None:
        headers = {"User-Agent": "TradeCatTUI/rss"}

        while not self._stop.is_set():
            if self._paused.is_set():
                self._wake.clear()
                self._stop.wait(timeout=0.2)
                continue

            started = time.time()
            self._refresh_once(started=started, headers=headers)
            finished_at = time.time()
            elapsed = finished_at - started
            sleep_s = max(0.2, self._refresh_s - elapsed)
            self._wake.clear()
            if sleep_s > 0:
                self._wake.wait(timeout=sleep_s)



# === NewsWatch+display ===

class NewsWatchItem:
    symbol: str
    market: str
    name: str
    price: float | None
    pct: float | None


def _news_time_text(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
    except Exception:
        return "--:--:--"


def _news_age_text(now_ts: float, ts: float) -> str:
    age_s = max(0, int(now_ts - float(ts)))
    if age_s < 60:
        return f"{age_s}s"
    minutes, _ = divmod(age_s, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _collect_news_watch_items(
    quote_cfgs: QuoteConfigs,
    quote_state_us: QuoteBookState,
    quote_state_hk: QuoteBookState,
    quote_state_cn: QuoteBookState,
    quote_state_crypto: QuoteBookState,
) -> list[NewsWatchItem]:
    picks: list[tuple[str, str]] = []
    picks.extend([("crypto_spot", s) for s in list(quote_cfgs.crypto.symbols)[:3]])
    picks.extend([("us_stock", s) for s in list(quote_cfgs.us.symbols)[:3]])
    picks.extend([("hk_stock", s) for s in list(quote_cfgs.hk.symbols)[:2]])
    picks.extend([("cn_stock", s) for s in list(quote_cfgs.cn.symbols)[:2]])

    out: list[NewsWatchItem] = []
    seen: set[str] = set()
    for market, sym_raw in picks:
        sym = (sym_raw or "").strip().upper()
        if not sym or f"{market}:{sym}" in seen:
            continue
        seen.add(f"{market}:{sym}")
        if market == "crypto_spot":
            state = quote_state_crypto.entries.get(sym)
        elif market == "us_stock":
            state = quote_state_us.entries.get(sym)
        elif market == "hk_stock":
            state = quote_state_hk.entries.get(sym)
        else:
            state = quote_state_cn.entries.get(sym)
        q = state.quote if state else None
        name = _display_name(sym, q, market)
        price = float(q.price) if q is not None else None
        pct: float | None = None
        if q is not None and q.prev_close:
            pct = (float(q.price) - float(q.prev_close)) / float(q.prev_close) * 100.0
        out.append(NewsWatchItem(symbol=sym, market=market, name=name, price=price, pct=pct))
    return out


def _news_source_group_label(group: str, tier: str) -> str:
    normalized_group = (group or "").strip().lower()
    normalized_tier = (tier or "").strip().lower()
    if normalized_tier == PRIMARY_TIER or normalized_group == CORE_GROUP:
        return _NEWS_SOURCE_FILTER_PRIMARY
    if normalized_tier == SUPPLEMENTAL_TIER:
        return _NEWS_SOURCE_FILTER_SUPPLEMENTAL
    return "--"


def _news_source_filter_options(items: list[NewsItem]) -> tuple[str, ...]:
    options: list[str] = [_NEWS_SOURCE_FILTER_ALL]
    seen_codes: set[str] = set()
    has_primary = False
    has_supplemental = False
    codes: list[str] = []

    for item in items:
        if (item.source_tier or "").strip().lower() == PRIMARY_TIER:
            has_primary = True
        elif (item.source_tier or "").strip().lower() == SUPPLEMENTAL_TIER:
            has_supplemental = True

        code = (item.source or "").strip().upper()
        if code and code not in seen_codes:
            seen_codes.add(code)
            codes.append(code)

    if has_primary:
        options.append(_NEWS_SOURCE_FILTER_PRIMARY)
    if has_supplemental:
        options.append(_NEWS_SOURCE_FILTER_SUPPLEMENTAL)
    options.extend(sorted(codes))
    return tuple(options)


def _matches_news_source_filter(item: NewsItem, source_filter: str) -> bool:
    current = (source_filter or "").strip()
    if not current or current == _NEWS_SOURCE_FILTER_ALL:
        return True
    if current == _NEWS_SOURCE_FILTER_PRIMARY:
        return (item.source_tier or "").strip().lower() == PRIMARY_TIER
    if current == _NEWS_SOURCE_FILTER_SUPPLEMENTAL:
        return (item.source_tier or "").strip().lower() == SUPPLEMENTAL_TIER
    return (item.source or "").strip().upper() == current.upper()


def _filter_news_items(
    items: list[NewsItem],
    *,
    now_ts: float,
    category: str,
    window_h: int,
    search_query: str,
    source_filter: str = _NEWS_SOURCE_FILTER_ALL,
    watch_symbol: str = "",
) -> list[NewsItem]:
    max_age = max(1, int(window_h)) * 3600
    query = (search_query or "").strip().lower()
    ws = (watch_symbol or "").strip().upper()
    filtered: list[NewsItem] = []
    for item in items:
        age_s = now_ts - item.published_at
        if age_s < 0 or age_s > max_age:
            continue
        if category != "全部" and item.category != category:
            continue
        if not _matches_news_source_filter(item, source_filter):
            continue
        if ws and ws not in item.symbols and ws not in item.impact_assets:
            # RSS feeds may not provide structured symbol tags yet; fall back to fuzzy matching.
            hay = f"{item.title} {item.summary} {item.url}".upper()
            keywords = {ws}
            if "_" in ws:
                keywords.update({p for p in ws.split("_") if p})
            # A/H-share common prefixes.
            if (ws.startswith("SH") or ws.startswith("SZ")) and len(ws) > 2:
                keywords.add(ws[2:])
            if not any(k and k in hay for k in keywords):
                continue
        if query:
            haystack = " ".join(
                [
                    item.title,
                    item.summary,
                    item.source,
                    item.category,
                    " ".join(item.symbols),
                    " ".join(item.impact_assets),
                ]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(item)
    return filtered


def _build_news_events(items: list[NewsItem]) -> list[NewsEvent]:
    return cluster_news_items(items)



def _news_source_options(news_poller=None):
    """Return available news source filter options."""
    all_items: list[NewsItem] = []
    if news_poller is not None:
        all_items = list(news_poller.snapshot().items)
    return _news_source_filter_options(all_items)


def _news_counts(news_state=None, news_poller=None, now_ts=None):
    """Return (index, item_count) for the current news view."""
    ts = float(time.time() if now_ts is None else now_ts)
    category = _NEWS_CATEGORIES[min(max(0, news_state.category_idx), len(_NEWS_CATEGORIES) - 1)]
    window_h = _NEWS_WINDOWS_H[min(max(0, news_state.window_idx), len(_NEWS_WINDOWS_H) - 1)]
    source_options = _news_source_options(news_poller)
    source_filter = source_options[min(max(0, news_state.source_idx), len(source_options) - 1)] if source_options else _NEWS_SOURCE_FILTER_ALL
    all_items: list[NewsItem] = []
    if news_poller is not None:
        all_items = list(news_poller.snapshot().items)
    items = _filter_news_items(
        all_items,
        now_ts=ts,
        category=category,
        window_h=window_h,
        search_query=news_state.search_query,
        source_filter=source_filter,
    )
    events = _build_news_events(items)
    return 0, len(events)


# === draw_market_news ===

def _draw_market_news(
    stdscr,
    state: NewsPageState,
    news_snapshot: NewsFeedSnapshot | None,
    quote_cfgs: QuoteConfigs,
    quote_state_us: QuoteBookState,
    quote_state_hk: QuoteBookState,
    quote_state_cn: QuoteBookState,
    quote_state_crypto: QuoteBookState,
    colors: dict[str, int],
    w: int,
    h: int,
) -> None:
    key_hint = (
        "按键: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 5基金 | 6港股 | 7资讯 | Tab切Agent | "
        "/搜索 | f分类 | s来源 | w时间窗 | c清空"
    )
    _safe_addstr(stdscr, h - 1, 0, _truncate(key_hint, w))

    category = _NEWS_CATEGORIES[min(max(0, state.category_idx), len(_NEWS_CATEGORIES) - 1)]
    window_h = _NEWS_WINDOWS_H[min(max(0, state.window_idx), len(_NEWS_WINDOWS_H) - 1)]
    all_items = [] if news_snapshot is None else list(news_snapshot.items)
    source_options = _news_source_filter_options(all_items)
    state.source_idx = min(max(0, state.source_idx), max(0, len(source_options) - 1))
    source_filter = source_options[state.source_idx] if source_options else _NEWS_SOURCE_FILTER_ALL
    now_ts = time.time()
    feed_hint = "RSS(0)"
    sync_age = ""
    latest_age = ""
    health_hint = ""
    feed_err = ""
    if news_snapshot is not None:
        mode = (news_snapshot.mode or "").strip().upper() or "RSS"
        if mode == "RSS":
            feed_hint = f"RSS({len(news_snapshot.feeds)})"
        else:
            feed_hint = mode
        if news_snapshot.last_ok_at > 0:
            sync_age = _news_age_text(now_ts, news_snapshot.last_ok_at)
        if news_snapshot.latest_item_at > 0:
            latest_age = _news_age_text(now_ts, news_snapshot.latest_item_at)
        health = news_snapshot.health
        if health.available:
            health_hint = f" 健=H{int(health.healthy)}/F{int(health.failing)}/C{int(health.cooldown)}"
        feed_err = (news_snapshot.last_error or "").strip()
        if not feed_err and health.sample and (int(health.failing) > 0 or int(health.cooldown) > 0):
            feed_err = health.sample
    else:
        feed_err = "新闻源未配置"
    if feed_err:
        feed_err = _truncate(feed_err, 18)
    feed_status = f"源={feed_hint}"
    if sync_age:
        feed_status += f" 同步={sync_age}前"
    if latest_age:
        feed_status += f" 最新={latest_age}前"
    if health_hint:
        feed_status += health_hint
    if feed_err:
        feed_status += f" ERR={feed_err}"

    cmd_line = f"{feed_status}  搜索=/{state.search_query or ''}  分类=[{category}]  时间窗=[{window_h}h]"
    _safe_addstr(stdscr, 1, 0, _truncate(cmd_line, w))

    panel_top = 2
    panel_h = max(0, h - panel_top - 1)
    if panel_h < 10:
        _safe_addstr(stdscr, panel_top, 0, _truncate("资讯页: 终端高度不足（建议>=22行）", w))
        return

    top_h = int(round(panel_h * 0.66))
    top_h = max(8, min(top_h, panel_h - 5))
    bottom_y = panel_top + top_h
    bottom_h = panel_h - top_h
    if bottom_h < 4:
        return

    right_w = max(26, int(round(w * 0.28)))
    right_w = min(right_w, max(26, w - 44))
    mid_w = w - right_w
    mid_x = 0
    right_x = mid_w
    if mid_w < 44 or right_w < 26:
        return

    box_attr = curses.color_pair(colors.get("SRC", 0))
    _draw_box(stdscr, mid_x, panel_top, mid_w, top_h, box_attr)
    _draw_box(stdscr, right_x, panel_top, right_w, top_h, box_attr)
    _draw_box(stdscr, 0, bottom_y, w, bottom_h, box_attr)

    filtered_items = _filter_news_items(
        all_items,
        now_ts=now_ts,
        category=category,
        window_h=window_h,
        search_query=state.search_query,
        source_filter=source_filter,
    )
    events = _build_news_events(filtered_items)
    state.news_selected = min(max(0, state.news_selected), max(0, len(events) - 1))
    if state.news_selected < state.news_scroll:
        state.news_scroll = state.news_selected

    middle_focus = "*" if state.focus == "middle" else " "
    right_focus = "*" if state.focus == "right" else " "

    _safe_addstr(stdscr, panel_top, mid_x + 1, _truncate(f"[{middle_focus}] 新闻事件({len(events)})", mid_w - 2), curses.A_UNDERLINE)
    _safe_addstr(stdscr, panel_top, right_x + 1, _truncate(f"[{right_focus}] 事件影响", right_w - 2), curses.A_UNDERLINE)
    _safe_addstr(stdscr, bottom_y, 1, _truncate("详情", w - 2), curses.A_UNDERLINE)

    mid_inner_w = max(0, mid_w - 2)
    mid_body_top = panel_top + 1
    mid_body_h = max(0, top_h - 2)
    if mid_body_h <= 0:
        return

    mid_header = "时间     源   类别 强度 聚合    标题"
    _safe_addstr(stdscr, mid_body_top, mid_x + 1, _truncate(mid_header, mid_inner_w), curses.A_UNDERLINE)
    list_h = max(1, mid_body_h - 1)
    state.news_scroll = min(max(0, state.news_scroll), max(0, len(events) - 1))
    if state.news_selected >= state.news_scroll + list_h:
        state.news_scroll = state.news_selected - list_h + 1
    visible_events = events[state.news_scroll : state.news_scroll + list_h]

    if not visible_events:
        msg = "暂无匹配事件（可按 c 清空搜索）"
        if news_snapshot is not None:
            mode_label = (news_snapshot.mode or "").strip().upper() or "NEWS"
            if (news_snapshot.last_error or "").strip():
                msg = f"{mode_label} 暂无数据/拉取失败: {_truncate(news_snapshot.last_error, 26)}（可按 c 清空搜索）"
            elif news_snapshot.items:
                msg = "当前筛选条件下暂无匹配事件（可按 c 清空搜索）"
            else:
                msg = f"{mode_label} 暂无数据（等待刷新）"
        _safe_addstr(
            stdscr,
            mid_body_top + 1,
            mid_x + 1,
            _truncate(msg, mid_inner_w),
            curses.color_pair(colors.get("SRC", 0)),
        )
    for i, event in enumerate(visible_events):
        y = mid_body_top + 1 + i
        global_idx = state.news_scroll + i
        prefix = ">" if global_idx == state.news_selected else " "
        merge_hint = f"{event.article_count}条/{event.source_count}源"
        title = _truncate(event.primary_title, max(8, mid_inner_w - 34))
        line = (
            f"{prefix}{_news_time_text(event.last_updated_at):<8} "
            f"{event.primary_source[:4]:<4} {event.category[:2]:<2} {event.severity:<4} {merge_hint:<7} {title}"
        )
        attr = 0
        if event.severity == "HIGH":
            attr = curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD
        elif event.severity == "MID":
            attr = curses.color_pair(colors.get("ALERT", 0))
        else:
            attr = curses.color_pair(colors.get("SRC", 0))
        if global_idx == state.news_selected and state.focus == "middle":
            attr |= curses.A_REVERSE
        _safe_addstr(stdscr, y, mid_x + 1, _truncate(line, mid_inner_w), attr)

    selected_event = events[state.news_selected] if events else None
    right_inner_w = max(0, right_w - 2)
    right_row = panel_top + 1
    if selected_event is None:
        _safe_addstr(stdscr, right_row, right_x + 1, _truncate("暂无选中事件", right_inner_w), curses.color_pair(colors.get("SRC", 0)))
    else:
        lines = [
            f"事件等级: {selected_event.severity}",
            f"方向偏向: {selected_event.direction}",
            (
                f"代表源: {selected_event.primary_source}  "
                f"分组: {_news_source_group_label(selected_event.source_group, selected_event.source_tier)}  分类: {selected_event.category}"
            ),
            f"首次出现: {_news_age_text(now_ts, selected_event.first_seen_at)}前",
            f"最近更新: {_news_age_text(now_ts, selected_event.last_updated_at)}前",
            f"聚合规模: {selected_event.article_count}条 / {selected_event.source_count}源",
            f"Top来源: {', '.join(selected_event.top_sources[:4]) or '--'}",
            f"相关标的: {', '.join(selected_event.symbols[:4]) or '--'}",
            f"影响资产: {', '.join(selected_event.impact_assets[:4]) or '--'}",
            f"置信度: {selected_event.confidence:.2f}",
            f"建议动作: {selected_event.suggestion or '--'}",
        ]
        for line in lines:
            if right_row >= panel_top + top_h - 1:
                break
            _safe_addstr(stdscr, right_row, right_x + 1, _truncate(line, right_inner_w))
            right_row += 1
    detail_inner_w = max(0, w - 2)
    detail_top = bottom_y + 1
    detail_h = max(0, bottom_h - 2)
    if detail_h <= 0:
        return
    if selected_event is None:
        _safe_addstr(stdscr, detail_top, 1, _truncate("无事件详情", detail_inner_w), curses.color_pair(colors.get("SRC", 0)))
        return

    detail_lines = [
        f"标题: {selected_event.primary_title}",
        f"摘要: {selected_event.primary_summary or '--'}",
        (
            f"来源: {selected_event.primary_source}   首次: {_news_time_text(selected_event.first_seen_at)}   "
            f"更新: {_news_time_text(selected_event.last_updated_at)}"
        ),
        f"聚类: {selected_event.article_count}条 / {selected_event.source_count}源   Top={', '.join(selected_event.top_sources[:5]) or '--'}",
        f"URL: {selected_event.primary_url or '--'}",
        (
            f"标签: [{selected_event.category}][{selected_event.severity}] "
            f"symbols={','.join(selected_event.symbols[:5]) or '--'} "
            f"impact={','.join(selected_event.impact_assets[:5]) or '--'}"
        ),
    ]
    for i, line in enumerate(detail_lines[:detail_h]):
        _safe_addstr(stdscr, detail_top + i, 1, _truncate(line, detail_inner_w))

