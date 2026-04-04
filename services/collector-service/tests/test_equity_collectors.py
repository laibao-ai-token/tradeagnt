import unittest
from datetime import datetime

from src.collectors.equity.cn import AKShareCandleFetcher, CNEquityCollector
from src.collectors.equity.hk import HKEquityCollector, TencentHKQuoteFetcher
from src.collectors.equity.us import USEquityCollector, YFinanceCandleFetcher


class _FakeFrame(object):
    def __init__(self, rows):
        self._rows = list(rows)
        self.empty = not self._rows

    def reset_index(self):
        return self

    def tail(self, size):
        return _FakeFrame(self._rows[-int(size):])

    def to_dict(self, orient):
        if orient != "records":
            raise AssertionError("unexpected orient: {0}".format(orient))
        return list(self._rows)

    def __len__(self):
        return len(self._rows)


class _FakeTicker(object):
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(dict(kwargs))
        return _FakeFrame(self._rows)


class _FakeAKShare(object):
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def stock_zh_a_hist_min_em(self, **kwargs):
        self.calls.append(dict(kwargs))
        return _FakeFrame(self._rows)


class _FakeWriter(object):
    def __init__(self):
        self.calls = []

    def upsert_equity_1m(self, market, rows, ingest_batch_id, source):
        payload = [dict(row) for row in rows]
        self.calls.append(
            {
                "market": market,
                "rows": payload,
                "ingest_batch_id": ingest_batch_id,
                "source": source,
            }
        )
        return len(payload)

    def close(self):
        return None


def _build_config(us_provider="yfinance", cn_provider="akshare", hk_provider="tencent"):
    return type(
        "Config",
        (),
        {
            "equity": type(
                "Equity",
                (),
                {
                    "enabled": True,
                    "interval": "1m",
                    "limit": 2,
                    "us_provider": us_provider,
                    "cn_provider": cn_provider,
                    "hk_provider": hk_provider,
                    "us_symbols": ["AAPL"],
                    "cn_symbols": ["600519.SH"],
                    "hk_symbols": ["00700.HK"],
                },
            )(),
            "runtime": type("Runtime", (), {"http_proxy": ""})(),
        },
    )()


class EquityCollectorTests(unittest.TestCase):
    def setUp(self):
        from src.core.registry import ProviderRegistry

        self._registry = ProviderRegistry
        self._saved_registry = dict(ProviderRegistry._fetchers)

    def tearDown(self):
        self._registry._fetchers = dict(self._saved_registry)

    def test_us_equity_collector_fetches_yfinance_rows_and_writes(self):
        ticker = _FakeTicker(
            [
                {
                    "Datetime": datetime(2026, 3, 31, 13, 30, 0),
                    "Open": 100.0,
                    "High": 101.0,
                    "Low": 99.5,
                    "Close": 100.5,
                    "Volume": 1234,
                }
            ]
        )
        fetcher = YFinanceCandleFetcher(client_factory=lambda symbol: ticker)
        writer = _FakeWriter()
        collector = USEquityCollector(
            config=_build_config(),
            writer=writer,
            batch_start=lambda **kwargs: 11,
            fetcher=fetcher,
        )

        written = collector.run_once(symbols=["AAPL"])

        self.assertEqual(1, written)
        self.assertEqual(1, len(writer.calls))
        self.assertEqual("us_stock", writer.calls[0]["market"])
        self.assertEqual("yfinance", writer.calls[0]["source"])
        row = writer.calls[0]["rows"][0]
        self.assertEqual("us", row["exchange"])
        self.assertEqual("AAPL", row["symbol"])
        self.assertEqual(100.5, row["close"])
        self.assertEqual(datetime(2026, 3, 31, 13, 30, 0), row["open_time"])

    def test_cn_equity_collector_fetches_akshare_rows_and_writes(self):
        api = _FakeAKShare(
            [
                {
                    "时间": "2026-03-31 09:30:00",
                    "开盘": 10.0,
                    "最高": 11.0,
                    "最低": 9.5,
                    "收盘": 10.5,
                    "成交量": 200,
                    "成交额": 2000,
                }
            ]
        )
        fetcher = AKShareCandleFetcher(api=api)
        writer = _FakeWriter()
        collector = CNEquityCollector(
            config=_build_config(),
            writer=writer,
            batch_start=lambda **kwargs: 12,
            fetcher=fetcher,
        )

        written = collector.run_once(symbols=["600519.SH"])

        self.assertEqual(1, written)
        self.assertEqual(1, len(api.calls))
        self.assertEqual(1, len(writer.calls))
        self.assertEqual("cn_stock", writer.calls[0]["market"])
        self.assertEqual("akshare", writer.calls[0]["source"])
        row = writer.calls[0]["rows"][0]
        self.assertEqual("sse", row["exchange"])
        self.assertEqual("600519", row["symbol"])
        self.assertEqual(10.5, row["close"])

    def test_hk_equity_collector_fetches_tencent_rows_and_writes(self):
        fetcher = TencentHKQuoteFetcher(
            fetch_var=lambda code: (
                "100~腾讯控股~00700~520.000~521.000~519.500~10000~0~0~520.000~0~0~0~0~0~0~0~0~0~520.000~0~0~0~0~0~0~0~0~0~"
                "10000~2026/03/31 15:05:11~-1.000~-0.19~521.000~518.000~520.000~10000~5200000.000~HKD~1~30"
            )
        )
        writer = _FakeWriter()
        collector = HKEquityCollector(
            config=_build_config(),
            writer=writer,
            batch_start=lambda **kwargs: 13,
            fetcher=fetcher,
        )

        written = collector.run_once(symbols=["00700.HK"])

        self.assertEqual(1, written)
        self.assertEqual(1, len(writer.calls))
        self.assertEqual("hk_stock", writer.calls[0]["market"])
        self.assertEqual("tencent", writer.calls[0]["source"])
        row = writer.calls[0]["rows"][0]
        self.assertEqual("hkex", row["exchange"])
        self.assertEqual("00700", row["symbol"])
        self.assertEqual(520.0, row["close"])


if __name__ == "__main__":
    unittest.main()
