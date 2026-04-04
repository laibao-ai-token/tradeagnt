import unittest
from datetime import datetime, timezone

from src.collectors.news.rss import RssNewsCollector, parse_feed


class _FakeWriter(object):
    def __init__(self):
        self.calls = []

    def insert_articles(self, articles, ingest_batch_id):
        payload = [dict(article) for article in articles]
        self.calls.append({"articles": payload, "ingest_batch_id": ingest_batch_id})
        return len(payload)

    def close(self):
        return None


def _build_config(feeds=None):
    return type(
        "Config",
        (),
        {
            "runtime": type("Runtime", (), {"http_proxy": ""})(),
            "news": type(
                "News",
                (),
                {
                    "enabled": True,
                    "feeds": list(feeds or ["https://example.com/feed.xml"]),
                    "limit": 20,
                    "window_hours": 72,
                    "timeout_seconds": 10,
                    "retention_hours": 24,
                    "retention_cleanup_interval_seconds": 600,
                },
            )(),
        },
    )()


class NewsRssCollectorTests(unittest.TestCase):
    def test_parse_feed_extracts_rss_item(self):
        parsed = parse_feed(
            """<?xml version="1.0" encoding="utf-8"?>
            <rss version="2.0">
              <channel>
                <title>Example Feed</title>
                <item>
                  <title>Fed keeps rates unchanged</title>
                  <link>https://example.com/story</link>
                  <pubDate>Tue, 31 Mar 2026 08:00:00 GMT</pubDate>
                  <description><![CDATA[Macro update]]></description>
                  <category>macro</category>
                </item>
              </channel>
            </rss>"""
        )

        self.assertEqual("Example Feed", parsed["title"])
        self.assertEqual(1, len(parsed["entries"]))
        self.assertEqual("Fed keeps rates unchanged", parsed["entries"][0]["title"])
        self.assertEqual("https://example.com/story", parsed["entries"][0]["url"])
        self.assertEqual(datetime(2026, 3, 31, 8, 0, tzinfo=timezone.utc), parsed["entries"][0]["published_at"])

    def test_rss_news_collector_fetches_articles_and_writes_to_news_writer(self):
        writer = _FakeWriter()
        collector = RssNewsCollector(
            config=_build_config(),
            writer=writer,
            batch_start=lambda **kwargs: 31,
            fetch_text=lambda feed_url, timeout_s, proxy="": """<?xml version="1.0" encoding="utf-8"?>
                <rss version="2.0">
                  <channel>
                    <title>Example Feed</title>
                    <item>
                      <title>NVDA rallies on AI demand</title>
                      <link>https://example.com/nvda</link>
                      <pubDate>Tue, 31 Mar 2026 09:15:00 GMT</pubDate>
                      <description><![CDATA[Chip stocks higher]]></description>
                      <category>equity</category>
                    </item>
                  </channel>
                </rss>""",
        )

        inserted = collector.run_once()

        self.assertEqual(1, inserted)
        self.assertEqual(1, len(writer.calls))
        self.assertEqual(31, writer.calls[0]["ingest_batch_id"])
        article = writer.calls[0]["articles"][0]
        self.assertEqual("example.com", article["source"])
        self.assertEqual("https://example.com/nvda", article["url"])
        self.assertEqual("NVDA rallies on AI demand", article["title"])
        self.assertEqual(["equity"], article["categories"])


if __name__ == "__main__":
    unittest.main()
