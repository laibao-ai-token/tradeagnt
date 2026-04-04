import unittest
import asyncio
from datetime import datetime
import sys
import types

from src.collectors.crypto import ws as ws_module
from src.adapters import cryptofeed as cryptofeed_module


class _FakeTimescale(object):
    def __init__(self):
        self.upsert_calls = []
        self.closed = False

    def upsert_candles(self, interval, rows):
        payload = [dict(row) for row in rows]
        self.upsert_calls.append((interval, payload))
        return len(payload)

    def close(self):
        self.closed = True


class _FakeMetrics(object):
    def __init__(self):
        self.inc_calls = []

    def inc(self, name, value=1):
        self.inc_calls.append((name, value))


class _FakeCandleEvent(object):
    def __init__(
        self,
        symbol,
        timestamp,
        open_price,
        high,
        low,
        close,
        volume,
        quote_volume=None,
        taker_buy_volume=None,
        taker_buy_quote_volume=None,
        trade_count=None,
    ):
        self.symbol = symbol
        self.timestamp = timestamp
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.quote_volume = quote_volume
        self.taker_buy_volume = taker_buy_volume
        self.taker_buy_quote_volume = taker_buy_quote_volume
        self.trade_count = trade_count


def _build_config(provider="binance_futures_ws", symbols=None):
    return type(
        "Config",
        (),
        {
            "runtime": type(
                "Runtime",
                (),
                {
                    "http_proxy": "http://proxy.local:7890",
                    "gap_check_interval": 600,
                },
            )(),
            "crypto_kline": type(
                "CryptoKline",
                (),
                {
                    "enabled": True,
                    "provider": provider,
                    "symbols": list(symbols or []),
                    "db_exchange": "binance_futures_um",
                    "ws_source": "binance_ws",
                    "ccxt_exchange": "binance",
                    "gate_poll_interval_seconds": 10,
                    "gate_timeout_seconds": 5,
                    "gate_workers": 2,
                    "gate_db_exchange": "gate_spot",
                },
            )(),
        },
    )()


class WSCollectorTests(unittest.TestCase):
    def setUp(self):
        self.original_load_symbols = getattr(ws_module, "load_symbols", None)
        self.original_preload_symbols = getattr(ws_module, "preload_symbols", None)
        self.original_get_configured_symbols = getattr(ws_module, "get_configured_symbols", None)
        self.original_fetch_spot_candles = getattr(ws_module, "fetch_spot_candles", None)

    def tearDown(self):
        if self.original_load_symbols is not None:
            ws_module.load_symbols = self.original_load_symbols
        if self.original_preload_symbols is not None:
            ws_module.preload_symbols = self.original_preload_symbols
        ws_module.get_configured_symbols = self.original_get_configured_symbols
        if self.original_fetch_spot_candles is not None:
            ws_module.fetch_spot_candles = self.original_fetch_spot_candles

    def test_futures_provider_loads_exchange_symbols_and_preloads_mapping(self):
        preload_calls = []
        ws_module.load_symbols = lambda exchange: ["BTCUSDT", "ETHUSDT"]
        ws_module.preload_symbols = lambda symbols: preload_calls.append(list(symbols))
        ws_module.get_configured_symbols = lambda: None

        collector = ws_module.WSCollector(
            config=_build_config(provider="binance_futures_ws"),
            timescale=_FakeTimescale(),
            metrics_client=_FakeMetrics(),
        )

        self.assertEqual(
            {
                "BTC-USDT-PERP": "BTCUSDT",
                "ETH-USDT-PERP": "ETHUSDT",
            },
            collector._symbols,
        )
        self.assertEqual([["BTCUSDT", "ETHUSDT"]], preload_calls)

    def test_on_candle_writes_1m_row_with_exchange_and_source(self):
        ws_module.load_symbols = lambda exchange: ["BTCUSDT"]
        ws_module.preload_symbols = lambda symbols: None
        ws_module.get_configured_symbols = lambda: None
        metrics_client = _FakeMetrics()
        timescale = _FakeTimescale()

        collector = ws_module.WSCollector(
            config=_build_config(provider="binance_futures_ws"),
            timescale=timescale,
            metrics_client=metrics_client,
        )
        collector.MAX_BUFFER = 1

        collector._on_candle_sync(
            _FakeCandleEvent(
                symbol="BTC-USDT-PERP",
                timestamp=1774864800,
                open_price=100.0,
                high=101.0,
                low=99.5,
                close=100.5,
                volume=12.0,
                quote_volume=34.0,
                taker_buy_volume=5.0,
                taker_buy_quote_volume=7.0,
                trade_count=8,
            )
        )

        self.assertEqual(1, len(timescale.upsert_calls))
        interval, rows = timescale.upsert_calls[0]
        self.assertEqual("1m", interval)
        self.assertEqual(1, len(rows))
        self.assertEqual("binance_futures_um", rows[0]["exchange"])
        self.assertEqual("BTCUSDT", rows[0]["symbol"])
        self.assertEqual(datetime.utcfromtimestamp(1774864800), rows[0]["bucket_ts"])
        self.assertEqual("binance_ws", rows[0]["source"])
        self.assertEqual(34.0, rows[0]["quote_volume"])
        self.assertEqual(8, rows[0]["trade_count"])
        self.assertEqual([("rows_written", 1)], metrics_client.inc_calls)

    def test_gate_poll_once_writes_only_closed_rows(self):
        ws_module.get_configured_symbols = lambda: None
        timescale = _FakeTimescale()
        metrics_client = _FakeMetrics()

        collector = ws_module.WSCollector(
            config=_build_config(provider="gate_spot_poll", symbols=["BTCUSDT"]),
            timescale=timescale,
            metrics_client=metrics_client,
        )

        ws_module.fetch_spot_candles = lambda currency_pair, interval="1m", limit=2, timeout_s=10.0: [
            ws_module.GateSpotCandle(
                ts=1774864800,
                quote_volume=22.0,
                close=100.5,
                high=101.0,
                low=99.5,
                open=100.0,
                volume=12.0,
                is_closed=True,
            ),
            ws_module.GateSpotCandle(
                ts=1774864860,
                quote_volume=30.0,
                close=101.5,
                high=102.0,
                low=100.5,
                open=101.0,
                volume=15.0,
                is_closed=False,
            ),
        ]

        written = collector._poll_gate_spot_once()

        self.assertEqual(1, written)
        self.assertEqual(1, len(timescale.upsert_calls))
        interval, rows = timescale.upsert_calls[0]
        self.assertEqual("1m", interval)
        self.assertEqual(1, len(rows))
        self.assertEqual("gate_spot", rows[0]["exchange"])
        self.assertEqual("BTCUSDT", rows[0]["symbol"])
        self.assertEqual([("rows_written", 1)], metrics_client.inc_calls)

    def test_gate_spot_candle_normalizes_text_closed_flag(self):
        candle = ws_module.GateSpotCandle(
            ts=1774864800,
            quote_volume=22.0,
            close=100.5,
            high=101.0,
            low=99.5,
            open=100.0,
            volume=12.0,
            is_closed="false",
        )

        self.assertFalse(candle.is_closed)

    def test_binance_ws_adapter_tolerates_none_raw_metrics(self):
        callback_events = []
        adapter = ws_module.BinanceWSAdapter()
        adapter.subscribe(["BTC-USDT-PERP"], callback_events.append)

        candle = type(
            "Candle",
            (),
            {
                "closed": True,
                "raw": {"k": {"q": None, "V": None, "Q": None}},
                "symbol": "BTC-USDT-PERP",
                "start": 1774864800,
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "volume": 12.0,
                "trades": 8,
            },
        )()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(adapter._on_candle(candle, 0.0))
        finally:
            loop.close()

        self.assertEqual(1, len(callback_events))
        self.assertEqual(0, float(callback_events[0].quote_volume))
        self.assertEqual(0, float(callback_events[0].taker_buy_volume))
        self.assertEqual(0, float(callback_events[0].taker_buy_quote_volume))

    def test_build_feedhandler_config_includes_log_filename_and_level(self):
        config = cryptofeed_module.build_feedhandler_config("collector-test.log")

        self.assertEqual(False, config["uvloop"])
        self.assertEqual("INFO", config["log"]["level"])
        self.assertTrue(config["log"]["filename"].endswith("collector-test.log"))

    def test_binance_ws_adapter_run_passes_ws_proxy_and_http_proxy(self):
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
            sys.modules["cryptofeed.defines"] = types.SimpleNamespace(CANDLES="CANDLES")
            sys.modules["cryptofeed.exchanges"] = types.SimpleNamespace(BinanceFutures=_FakeExchange)

            adapter = cryptofeed_module.BinanceWSAdapter(http_proxy="http://proxy.local:7890")
            adapter.subscribe(["BTC-USDT-PERP"], lambda event: None)
            adapter.run()

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
