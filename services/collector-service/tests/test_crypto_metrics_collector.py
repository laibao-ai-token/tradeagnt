import unittest
from datetime import datetime
from decimal import Decimal

from src.collectors.crypto import metrics as metrics_module


class _FakeTimescale(object):
    def __init__(self):
        self.upsert_calls = []
        self.closed = False

    def upsert_metrics(self, rows):
        payload = [dict(row) for row in rows]
        self.upsert_calls.append(payload)
        return len(payload)

    def close(self):
        self.closed = True


class _FakeMetrics(object):
    def __init__(self):
        self.inc_calls = []
        self.set_calls = []

    def inc(self, name, value=1):
        self.inc_calls.append((name, value))

    def set(self, name, value):
        self.set_calls.append((name, value))


class _FakeResponse(object):
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error {0}".format(self.status_code))

    def json(self):
        return self._payload


class _FakeSession(object):
    def __init__(self, response_map):
        self.response_map = response_map
        self.calls = []

    def get(self, url, params=None, proxies=None, timeout=None):
        key = url.rsplit("/", 1)[-1]
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "proxies": dict(proxies or {}),
                "timeout": timeout,
            }
        )
        return self.response_map[key]


def _build_config(enabled=True, interval="5m"):
    return type(
        "Config",
        (),
        {
            "runtime": type(
                "Runtime",
                (),
                {
                    "http_proxy": "http://proxy.local:7890",
                },
            )(),
            "crypto_kline": type(
                "CryptoKline",
                (),
                {
                    "ccxt_exchange": "binance",
                    "db_exchange": "binance_futures_um",
                },
            )(),
            "crypto_metrics": type(
                "CryptoMetrics",
                (),
                {
                    "enabled": enabled,
                    "interval": interval,
                },
            )(),
        },
    )()


class MetricsCollectorTests(unittest.TestCase):
    def setUp(self):
        self.original_load_symbols = getattr(metrics_module, "load_symbols", None)

    def tearDown(self):
        if self.original_load_symbols is not None:
            metrics_module.load_symbols = self.original_load_symbols

    def test_collect_one_calls_five_endpoints_and_builds_row(self):
        session = _FakeSession(
            {
                "openInterestHist": _FakeResponse(
                    200,
                    [
                        {
                            "timestamp": 1774865100000,
                            "sumOpenInterest": "123.45",
                            "sumOpenInterestValue": "456.78",
                        }
                    ],
                ),
                "topLongShortPositionRatio": _FakeResponse(200, [{"longShortRatio": "1.11"}]),
                "topLongShortAccountRatio": _FakeResponse(200, [{"longShortRatio": "1.22"}]),
                "globalLongShortAccountRatio": _FakeResponse(200, [{"longShortRatio": "1.33"}]),
                "takerlongshortRatio": _FakeResponse(200, [{"buySellRatio": "0.88"}]),
            }
        )
        collector = metrics_module.MetricsCollector(
            config=_build_config(enabled=True, interval="5m"),
            timescale=_FakeTimescale(),
            session=session,
            metrics_client=_FakeMetrics(),
            workers=2,
        )

        row = collector._collect_one("btcusdt")

        self.assertEqual(5, len(session.calls))
        self.assertEqual("BTCUSDT", row["symbol"])
        self.assertEqual("binance_futures_um", row["exchange"])
        self.assertEqual(datetime.utcfromtimestamp(1774865100), row["create_time"])
        self.assertEqual(Decimal("123.45"), row["sum_open_interest"])
        self.assertEqual(Decimal("456.78"), row["sum_open_interest_value"])
        self.assertEqual(Decimal("1.22"), row["count_toptrader_long_short_ratio"])
        self.assertEqual(Decimal("1.11"), row["sum_toptrader_long_short_ratio"])
        self.assertEqual(Decimal("1.33"), row["count_long_short_ratio"])
        self.assertEqual(Decimal("0.88"), row["sum_taker_long_short_vol_ratio"])
        self.assertEqual("binance_api", row["source"])
        self.assertTrue(all(call["params"]["period"] == "5m" for call in session.calls))
        self.assertTrue(all(call["timeout"] == 10 for call in session.calls))
        self.assertTrue(all(call["proxies"]["http"] == "http://proxy.local:7890" for call in session.calls))

    def test_run_once_returns_zero_when_disabled(self):
        collector = metrics_module.MetricsCollector(
            config=_build_config(enabled=False, interval="5m"),
            timescale=_FakeTimescale(),
            session=_FakeSession({}),
            metrics_client=_FakeMetrics(),
        )

        written = collector.run_once(symbols=["BTCUSDT"])

        self.assertEqual(0, written)
        self.assertEqual([], collector._ts.upsert_calls)

    def test_run_once_loads_symbols_collects_and_saves_rows(self):
        session = _FakeSession(
            {
                "openInterestHist": _FakeResponse(
                    200,
                    [
                        {
                            "timestamp": 1774865100000,
                            "sumOpenInterest": "123.45",
                            "sumOpenInterestValue": "456.78",
                        }
                    ],
                ),
                "topLongShortPositionRatio": _FakeResponse(200, [{"longShortRatio": "1.11"}]),
                "topLongShortAccountRatio": _FakeResponse(200, [{"longShortRatio": "1.22"}]),
                "globalLongShortAccountRatio": _FakeResponse(200, [{"longShortRatio": "1.33"}]),
                "takerlongshortRatio": _FakeResponse(200, [{"buySellRatio": "0.88"}]),
            }
        )
        fake_timescale = _FakeTimescale()
        fake_metrics = _FakeMetrics()
        metrics_module.load_symbols = lambda exchange: ["BTCUSDT"]
        collector = metrics_module.MetricsCollector(
            config=_build_config(enabled=True, interval="5m"),
            timescale=fake_timescale,
            session=session,
            metrics_client=fake_metrics,
            workers=1,
        )

        written = collector.run_once()

        self.assertEqual(1, written)
        self.assertEqual(1, len(fake_timescale.upsert_calls))
        self.assertEqual(1, len(fake_timescale.upsert_calls[0]))
        self.assertEqual(("rows_written", 1), fake_metrics.inc_calls[-1])

    def test_collect_one_tolerates_non_list_optional_payloads(self):
        session = _FakeSession(
            {
                "openInterestHist": _FakeResponse(
                    200,
                    [
                        {
                            "timestamp": 1774865100000,
                            "sumOpenInterest": "123.45",
                            "sumOpenInterestValue": "456.78",
                        }
                    ],
                ),
                "topLongShortPositionRatio": _FakeResponse(200, {"bad": True}),
                "topLongShortAccountRatio": _FakeResponse(200, []),
                "globalLongShortAccountRatio": _FakeResponse(200, None),
                "takerlongshortRatio": _FakeResponse(200, [{"buySellRatio": "0.88"}]),
            }
        )
        collector = metrics_module.MetricsCollector(
            config=_build_config(enabled=True, interval="5m"),
            timescale=_FakeTimescale(),
            session=session,
            metrics_client=_FakeMetrics(),
            workers=1,
        )

        row = collector._collect_one("BTCUSDT")

        self.assertIsNotNone(row)
        self.assertIsNone(row["count_toptrader_long_short_ratio"])
        self.assertIsNone(row["sum_toptrader_long_short_ratio"])
        self.assertIsNone(row["count_long_short_ratio"])
        self.assertEqual(Decimal("0.88"), row["sum_taker_long_short_vol_ratio"])


if __name__ == "__main__":
    unittest.main()
