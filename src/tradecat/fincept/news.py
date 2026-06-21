"""
FinceptTerminal 新闻模块封装
提供多数据源新闻获取
"""

import requests
import time
from datetime import datetime
from typing import List, Optional


class NewsItem:
    """新闻条目"""
    def __init__(self, title: str, content: str, source: str, time: str, url: str = ""):
        self.title = title
        self.content = content
        self.source = source
        self.time = time
        self.url = url

    def to_dict(self):
        return {
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "time": self.time,
            "url": self.url,
        }


class FinceptNews:
    """多数据源新闻获取"""

    def __init__(self):
        self.headers = {"User-Agent": "Mozilla/5.0"}

    def fetch_wallstreetcn(self, limit: int = 10) -> List[NewsItem]:
        """华尔街见闻"""
        try:
            r = requests.get(
                f"https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit={limit}",
                headers=self.headers,
                timeout=10
            )
            data = r.json()
            items = []
            for item in data.get('data', {}).get('items', []):
                news = NewsItem(
                    title=item.get('title', ''),
                    content=item.get('content', ''),
                    source="华尔街见闻",
                    time=datetime.fromtimestamp(item.get('display_time', 0)).strftime('%Y-%m-%d %H:%M'),
                    url=item.get('url', '')
                )
                items.append(news)
            return items
        except Exception as e:
            print(f"华尔街见闻获取失败: {e}")
            return []

    def fetch_tonghuashun(self, limit: int = 10) -> List[NewsItem]:
        """同花顺快讯"""
        try:
            r = requests.get(
                "https://news.10jqka.com.cn/tapp/news/push/stock/",
                headers=self.headers,
                timeout=10
            )
            data = r.json()
            items = []
            for item in data.get('data', {}).get('list', [])[:limit]:
                news = NewsItem(
                    title=item.get('title', ''),
                    content=item.get('digest', ''),
                    source="同花顺",
                    time=item.get('ctime', ''),
                    url=item.get('url', '')
                )
                items.append(news)
            return items
        except Exception as e:
            print(f"同花顺获取失败: {e}")
            return []

    def fetch_sina(self, limit: int = 10) -> List[NewsItem]:
        """新浪7x24"""
        try:
            r = requests.get(
                f"https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size={limit}",
                headers=self.headers,
                timeout=10
            )
            data = r.json()
            items = []
            for item in data.get('result', {}).get('data', {}).get('feed', {}).get('list', []):
                news = NewsItem(
                    title=item.get('tag', ''),
                    content=item.get('rich_text', ''),
                    source="新浪7x24",
                    time=item.get('create_time', ''),
                    url=item.get('url', '')
                )
                items.append(news)
            return items
        except Exception as e:
            print(f"新浪7x24获取失败: {e}")
            return []

    def fetch_all(self, limit_per_source: int = 5) -> List[NewsItem]:
        """从所有数据源获取新闻"""
        all_news = []

        # 并行获取
        sources = [
            self.fetch_wallstreetcn,
            self.fetch_tonghuashun,
            self.fetch_sina,
        ]

        for source_func in sources:
            try:
                news = source_func(limit_per_source)
                all_news.extend(news)
            except Exception as e:
                print(f"获取失败: {e}")

        # 按时间排序
        all_news.sort(key=lambda x: x.time, reverse=True)
        return all_news

    def fetch_by_keyword(self, keyword: str, limit: int = 10) -> List[NewsItem]:
        """按关键词搜索新闻"""
        all_news = self.fetch_all(limit * 2)
        filtered = [n for n in all_news if keyword.lower() in n.title.lower() or keyword.lower() in n.content.lower()]
        return filtered[:limit]
