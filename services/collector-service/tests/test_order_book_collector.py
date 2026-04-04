import unittest
from datetime import datetime
from decimal import Decimal
import sys
import types

from src.collectors.crypto import OrderBookCollector


def _build_config(symbols=None, depth=1000, http_proxy=""):
    return type(
        "Config",
        (),
        {
            "database": type("Database", (), {"raw_db_schema": "raw"})(),
            "runtime": type("Runtime", (), {"http_proxy": http_proxy})(),
            "crypto_kline": type(
                "KlineSection",
                (),
                {
                    "symbols": list(symbols or []),
                    "ccxt_exchange": "binance",
                    "ws_source": "binance_ws",
                    "db_exchange": "binance_futures_um",
                },
            )(),
            "crypto_orderbook": type(
                "OrderBookSection",
                (),
                {
                    "enabled": True,
                    "symbols": list(symbols or []),
                    "tick_interval": 1,
                    "full_interval": 5,
                    "depth": depth,
                },
            )(),
        },
    )()


class TestOrderBookCollector(unittest.TestCase):
    def test_load_symbols_prefers_orderbook_config(self):
        collector = OrderBookCollector(config=_build_config(symbols=["BTCUSDT"]), timescale=object())

        self.assertEqual({"BTC-USDT-PERP": "BTCUSDT"}, collector._symbols)

    def test_build_tick_row_uses_numeric_price_ordering(self):
        collector = OrderBookCollector(config=_build_config(symbols=["BTCUSDT"]), timescale=object())

        row = collector._build_tick_row(
            "BTCUSDT",
            datetime(2026, 3, 31, 0, 0, 0),
            {"49950": "2.0", "50000": "1.5"},
            {"50020": "0.5", "50010": "1.0"},
        )

        self.assertEqual(Decimal("50000.0"), row["bid1_price"])
        self.assertEqual(Decimal("50010.0"), row["ask1_price"])
        self.assertEqual(Decimal("1.9998"), row["spread_bps"])
        self.assertEqual(Decimal("0.4"), row["imbalance"])

    def test_build_full_row_respects_depth_limit(self):
        collector = OrderBookCollector(config=_build_config(symbols=["BTCUSDT"], depth=1), timescale=object())

        row = collector._build_full_row(
            "BTCUSDT",
            datetime(2026, 3, 31, 0, 0, 0),
            {"49950": "2.0", "50000": "1.5"},
            {"50020": "0.5", "50010": "1.0"},
            last_update_id=123,
        )

        self.assertEqual(123, row["last_update_id"])
        self.assertEqual(1, row["depth"])
        self.assertEqual('[["50000", "1.5"]]', row["bids"])
        self.assertEqual('[["50010", "1.0"]]', row["asks"])

    def test_close_stops_handler(self):
        collector = OrderBookCollector(config=_build_config(symbols=["BTCUSDT"]), timescale=object())
        calls = []

        collector._handler = type("Handler", (), {"stop": lambda self: calls.append("stop")})()
        collector.close()

        self.assertTrue(collector._stop_event.is_set())
        self.assertEqual(["stop"], calls)

    def test_orderbook_collector_exported(self):
        from src.collectors.crypto import __all__ as exports

        self.assertIn("OrderBookCollector", exports)

    def test_run_passes_full_feedhandler_log_config(self):
        collector = OrderBookCollector(
            config=_build_config(symbols=["BTCUSDT"], http_proxy="http://proxy.local:7890"),
            timescale=type("TS", (), {"close": lambda self: None})(),
        )
        captured = {}
        original_modules = {
            "cryptofeed": sys.modules.get("cryptofeed"),
            "cryptofeed.defines": sys.modules.get("cryptofeed.defines"),
            "cryptofeed.exchanges": sys.modules.get("cryptofeed.exchanges"),
        }

        class _FakeFeedHandler(object):
            def __init__(self, config=None):
                captured["config"] = config

            def add_feed(self, feed):
                captured["feed"] = feed

            def run(self):
                return None

            def stop(self):
                return None

        class _FakeExchange(object):
            websocket_endpoints = [type("Endpoint", (), {"options": {"compression": None}})()]

            def __init__(self, **kwargs):
                captured["feed_kwargs"] = kwargs

        try:
            sys.modules["cryptofeed"] = types.SimpleNamespace(FeedHandler=_FakeFeedHandler)
            sys.modules["cryptofeed.defines"] = types.SimpleNamespace(L2_BOOK="L2_BOOK")
            sys.modules["cryptofeed.exchanges"] = types.SimpleNamespace(BinanceFutures=_FakeExchange)

            collector.run()

            self.assertEqual(False, captured["config"]["uvloop"])
            self.assertEqual("INFO", captured["config"]["log"]["level"])
            self.assertIn("cryptofeed_orderbook.log", captured["config"]["log"]["filename"])
            self.assertEqual("http://proxy.local:7890", captured["feed_kwargs"]["http_proxy"])
            self.assertEqual("http://proxy.local:7890", captured["feed"].websocket_endpoints[0].options["proxy"])
        finally:
            for name, module in original_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
