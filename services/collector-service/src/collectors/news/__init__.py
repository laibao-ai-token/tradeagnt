"""News collector exports."""

from .rss import RssNewsCollector, RssNewsFetcher, parse_feed

__all__ = ["RssNewsCollector", "RssNewsFetcher", "parse_feed"]
