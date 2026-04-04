import io
import json
import signal
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

from src import __main__


class TestCollectorMain(unittest.TestCase):
    def test_runtime_state_wait_and_shutdown_hooks(self):
        state = __main__.RuntimeState()
        calls = []

        state.add_shutdown_hook(lambda: calls.append("hook"))

        self.assertFalse(state.wait(0))
        with redirect_stderr(io.StringIO()):
            state.request_shutdown(signal.SIGTERM)
        self.assertTrue(state.wait(0))
        self.assertEqual(["hook"], calls)

    def test_run_polling_collectors_loops_and_aggregates_totals(self):
        created = []

        class _FakePollingCollector(object):
            def __init__(self, values):
                self._values = list(values)
                self._index = 0
                self.closed = False

            def run_once(self):
                value = self._values[self._index]
                self._index += 1
                return value

            def close(self):
                self.closed = True

        def _factory(values):
            def _build():
                collector = _FakePollingCollector(values)
                created.append(collector)
                return collector

            return _build

        state = type(
            "State",
            (),
            {
                "shutdown_requested": False,
                "_waits": [False, True],
                "wait": lambda self, seconds: self._waits.pop(0),
            },
        )()

        result = __main__._run_polling_collectors(
            collector_name="equity",
            specs=(
                ("us", _factory([1, 3])),
                ("cn", _factory([2, 4])),
            ),
            state=state,
            interval_seconds=60,
            once=False,
            metric_key="written",
        )

        self.assertEqual("poll", result["mode"])
        self.assertEqual(2, result["iterations"])
        self.assertEqual(
            [
                {"component": "us", "written": 3},
                {"component": "cn", "written": 4},
            ],
            result["components"],
        )
        self.assertEqual(
            [
                {"component": "us", "written": 4},
                {"component": "cn", "written": 6},
            ],
            result["totals"],
        )
        self.assertTrue(all(collector.closed for collector in created))

    def test_run_crypto_collectors_registers_shutdown_hook_for_ws(self):
        crypto_module = sys.modules.get("src.collectors.crypto")
        if crypto_module is None:
            import src.collectors.crypto as crypto_module

        original_ws = crypto_module.WSCollector
        original_metrics = crypto_module.MetricsCollector
        stop_calls = []

        class _FakeWSCollector(object):
            def __init__(self, config=None):
                self.config = config

            def run(self):
                return None

            def stop(self):
                stop_calls.append("stop")

            def close(self):
                stop_calls.append("close")

        class _FakeMetricsCollector(object):
            def __init__(self, config=None):
                self.config = config

            def run_once(self):
                return 0

            def close(self):
                return None

        try:
            crypto_module.WSCollector = _FakeWSCollector
            crypto_module.MetricsCollector = _FakeMetricsCollector
            config = type(
                "Config",
                (),
                {
                    "runtime": type("Runtime", (), {"http_proxy": ""})(),
                    "crypto_kline": type(
                        "Section",
                        (),
                        {"enabled": True, "provider": "binance_futures_ws", "websocket_enabled": True},
                    )(),
                    "crypto_metrics": type("Section", (), {"enabled": False})(),
                },
            )()
            state = __main__.RuntimeState()

            __main__._run_crypto_collectors(config, state=state, once=False)
            with redirect_stderr(io.StringIO()):
                state.request_shutdown(signal.SIGTERM)

            self.assertIn("stop", stop_calls)
        finally:
            crypto_module.WSCollector = original_ws
            crypto_module.MetricsCollector = original_metrics

    def test_run_crypto_collectors_runs_backfill_before_metrics_and_ws(self):
        crypto_module = sys.modules.get("src.collectors.crypto")
        if crypto_module is None:
            import src.collectors.crypto as crypto_module

        original_backfiller = getattr(crypto_module, "DataBackfiller", None)
        original_ws = crypto_module.WSCollector
        original_metrics = crypto_module.MetricsCollector
        calls = []

        class _FakeBackfiller(object):
            def __init__(self, lookback_days=10, config=None, **kwargs):
                del kwargs
                self.lookback_days = lookback_days
                self.config = config
                calls.append(("backfill_init", lookback_days))

            def run_klines(self, symbols=None, interval="1m"):
                calls.append(("backfill_klines", list(symbols or []), interval))
                return {"filled": 3}

            def run_metrics(self, symbols=None):
                calls.append(("backfill_metrics", list(symbols or [])))
                return {"filled": 2}

            def close(self):
                calls.append(("backfill_close",))

        class _FakeWSCollector(object):
            def __init__(self, config=None):
                self.config = config

            def run(self):
                calls.append(("ws_run",))
                return None

            def stop(self):
                calls.append(("ws_stop",))

            def close(self):
                calls.append(("ws_close",))

        class _FakeMetricsCollector(object):
            def __init__(self, config=None):
                self.config = config

            def run_once(self):
                calls.append(("metrics_run_once",))
                return 4

            def close(self):
                calls.append(("metrics_close",))
                return None

        try:
            crypto_module.DataBackfiller = _FakeBackfiller
            crypto_module.WSCollector = _FakeWSCollector
            crypto_module.MetricsCollector = _FakeMetricsCollector
            config = type(
                "Config",
                (),
                {
                    "runtime": type(
                        "Runtime",
                        (),
                        {
                            "http_proxy": "",
                            "backfill_mode": "days",
                            "backfill_days": 7,
                            "backfill_start_date": "",
                        },
                    )(),
                    "crypto_kline": type(
                        "Section",
                        (),
                        {
                            "enabled": True,
                            "provider": "binance_futures_ws",
                            "websocket_enabled": True,
                            "symbols": ["BTCUSDT"],
                        },
                    )(),
                    "crypto_metrics": type("Section", (), {"enabled": True})(),
                },
            )()

            result = __main__._run_crypto_collectors(config, state=__main__.RuntimeState(), once=False)

            event_names = [item[0] for item in calls]
            self.assertEqual("crypto_backfill", result["components"][0]["component"])
            self.assertIn(("backfill_init", 7), calls)
            self.assertLess(event_names.index("backfill_klines"), event_names.index("metrics_run_once"))
            self.assertLess(event_names.index("metrics_run_once"), event_names.index("ws_run"))
        finally:
            if original_backfiller is None:
                delattr(crypto_module, "DataBackfiller")
            else:
                crypto_module.DataBackfiller = original_backfiller
            crypto_module.WSCollector = original_ws
            crypto_module.MetricsCollector = original_metrics

    def test_run_orderbook_collectors_registers_shutdown_hook(self):
        crypto_module = sys.modules.get("src.collectors.crypto")
        if crypto_module is None:
            import src.collectors.crypto as crypto_module

        original_orderbook = getattr(crypto_module, "OrderBookCollector", None)
        stop_calls = []

        class _FakeOrderBookCollector(object):
            def __init__(self, config=None):
                self.config = config

            def run(self):
                return None

            def stop(self):
                stop_calls.append("stop")

            def close(self):
                stop_calls.append("close")

        try:
            crypto_module.OrderBookCollector = _FakeOrderBookCollector
            config = type(
                "Config",
                (),
                {
                    "runtime": type("Runtime", (), {"http_proxy": ""})(),
                    "crypto_orderbook": type("Section", (), {"enabled": True})(),
                },
            )()
            state = __main__.RuntimeState()

            result = __main__._run_orderbook_collectors(config, state=state, once=False)
            with redirect_stderr(io.StringIO()):
                state.request_shutdown(signal.SIGTERM)

            self.assertEqual("orderbook", result["collector"])
            self.assertIn("stop", stop_calls)
        finally:
            if original_orderbook is None:
                delattr(crypto_module, "OrderBookCollector")
            else:
                crypto_module.OrderBookCollector = original_orderbook

    def test_help_mentions_only_and_exclude(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with self.assertRaises(SystemExit) as exc:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                __main__.main(["--help"])

        self.assertEqual(0, exc.exception.code)
        help_text = stdout.getvalue()
        self.assertIn("--only", help_text)
        self.assertIn("--exclude", help_text)

    def test_resolve_enabled_collectors_from_config(self):
        config = type(
            "Config",
            (),
            {
                "crypto_kline": type("Section", (), {"enabled": True})(),
                "crypto_metrics": type("Section", (), {"enabled": False})(),
                "crypto_orderbook": type("Section", (), {"enabled": True})(),
                "equity": type("Section", (), {"enabled": False})(),
                "fund_cn": type("Section", (), {"enabled": True})(),
                "news": type("Section", (), {"enabled": False})(),
            },
        )()

        enabled = __main__.resolve_enabled_collectors(config)

        self.assertEqual(["crypto", "orderbook", "fund_cn"], enabled)

    def test_only_and_exclude_filter_enabled_collectors(self):
        config = type(
            "Config",
            (),
            {
                "crypto_kline": type("Section", (), {"enabled": True})(),
                "crypto_metrics": type("Section", (), {"enabled": True})(),
                "crypto_orderbook": type("Section", (), {"enabled": True})(),
                "equity": type("Section", (), {"enabled": True})(),
                "fund_cn": type("Section", (), {"enabled": True})(),
                "news": type("Section", (), {"enabled": True})(),
                },
            )()

        enabled = __main__.resolve_enabled_collectors(
            config,
            only=["crypto", "fund_cn", "news"],
            exclude=["fund_cn"],
        )

        self.assertEqual(["crypto", "news"], enabled)

    def test_only_overrides_disabled_collectors_in_config(self):
        config = type(
            "Config",
            (),
            {
                "crypto_kline": type("Section", (), {"enabled": False})(),
                "crypto_metrics": type("Section", (), {"enabled": False})(),
                "crypto_orderbook": type("Section", (), {"enabled": False})(),
                "equity": type("Section", (), {"enabled": False})(),
                "fund_cn": type("Section", (), {"enabled": False})(),
                "news": type("Section", (), {"enabled": False})(),
            },
        )()

        enabled = __main__.resolve_enabled_collectors(
            config,
            only=["crypto", "fund_cn"],
        )

        self.assertEqual(["crypto", "fund_cn"], enabled)

    def test_config_style_names_are_accepted_as_aliases(self):
        config = type(
            "Config",
            (),
            {
                "crypto_kline": type("Section", (), {"enabled": False})(),
                "crypto_metrics": type("Section", (), {"enabled": False})(),
                "crypto_orderbook": type("Section", (), {"enabled": False})(),
                "equity": type("Section", (), {"enabled": False})(),
                "fund_cn": type("Section", (), {"enabled": False})(),
                "news": type("Section", (), {"enabled": False})(),
            },
        )()

        enabled = __main__.resolve_enabled_collectors(
            config,
            only=["crypto_kline", "fund_cn"],
        )

        self.assertEqual(["crypto", "fund_cn"], enabled)

    def test_unknown_collector_name_raises(self):
        config = type(
            "Config",
            (),
            {
                "crypto_kline": type("Section", (), {"enabled": True})(),
                "crypto_metrics": type("Section", (), {"enabled": False})(),
                "crypto_orderbook": type("Section", (), {"enabled": False})(),
                "equity": type("Section", (), {"enabled": False})(),
                "fund_cn": type("Section", (), {"enabled": False})(),
                "news": type("Section", (), {"enabled": False})(),
            },
        )()

        with self.assertRaises(ValueError):
            __main__.resolve_enabled_collectors(config, only=["broken"])

    def test_signal_handlers_request_shutdown(self):
        calls = []

        def fake_signal(signum, handler):
            calls.append((signum, handler))

        state = __main__.RuntimeState()
        original_signal = signal.signal
        try:
            signal.signal = fake_signal
            __main__.install_signal_handlers(state)
        finally:
            signal.signal = original_signal

        registered = dict(calls)
        self.assertIn(signal.SIGINT, registered)
        self.assertIn(signal.SIGTERM, registered)

        self.assertFalse(state.shutdown_requested)
        with redirect_stderr(io.StringIO()):
            registered[signal.SIGINT](signal.SIGINT, None)
        self.assertTrue(state.shutdown_requested)

    def test_main_starts_in_placeholder_mode(self):
        original_loader = __main__.load_config
        original_install = __main__.install_signal_handlers
        try:
            __main__.load_config = lambda: type(
                "Config",
                (),
                {
                    "crypto_kline": type("Section", (), {"enabled": True})(),
                    "crypto_metrics": type("Section", (), {"enabled": False})(),
                    "crypto_orderbook": type("Section", (), {"enabled": False})(),
                    "equity": type("Section", (), {"enabled": False})(),
                    "fund_cn": type("Section", (), {"enabled": True})(),
                    "news": type("Section", (), {"enabled": False})(),
                    "to_public_dict": lambda self: {"ok": True},
                },
            )()
            __main__.install_signal_handlers = lambda state: None
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = __main__.main(["--only", "crypto,fund_cn"])

            self.assertEqual(0, exit_code)
            self.assertIn("crypto", stdout.getvalue())
            self.assertIn("fund_cn", stdout.getvalue())
            self.assertIn("placeholder", stderr.getvalue())
        finally:
            __main__.load_config = original_loader
            __main__.install_signal_handlers = original_install

    def test_main_returns_cli_error_for_invalid_config(self):
        original_loader = __main__.load_config
        try:
            __main__.load_config = lambda: (_ for _ in ()).throw(ValueError("Invalid backfill mode: broken"))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with self.assertRaises(SystemExit) as exc:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    __main__.main(["--only", "crypto"])

            self.assertEqual(2, exc.exception.code)
            self.assertIn("Invalid backfill mode", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
        finally:
            __main__.load_config = original_loader

    def test_main_run_dispatches_supported_collectors(self):
        original_loader = __main__.load_config
        original_install = __main__.install_signal_handlers
        original_runners = getattr(__main__, "_build_runtime_runners", None)
        try:
            __main__.load_config = lambda: type(
                "Config",
                (),
                {
                    "crypto_kline": type("Section", (), {"enabled": True})(),
                    "crypto_metrics": type("Section", (), {"enabled": False})(),
                    "crypto_orderbook": type("Section", (), {"enabled": False})(),
                    "equity": type("Section", (), {"enabled": True})(),
                    "fund_cn": type("Section", (), {"enabled": False})(),
                    "news": type("Section", (), {"enabled": True})(),
                    "to_public_dict": lambda self: {"ok": True},
                },
            )()
            __main__.install_signal_handlers = lambda state: None
            __main__._build_runtime_runners = lambda cfg, state=None, once=False: {
                "crypto": lambda: {"collector": "crypto", "components": [{"component": "crypto_kline", "status": "completed"}]},
                "equity": lambda: {"collector": "equity", "components": [{"component": "us", "written": 1}]},
                "news": lambda: {"collector": "news", "components": [{"component": "rss", "inserted": 2}]},
            }
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = __main__.main(["--run", "--once", "--only", "crypto,news"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("run", payload["mode"])
            self.assertEqual(["crypto", "news"], payload["enabled_collectors"])
            self.assertEqual([], payload["unsupported_collectors"])
            self.assertEqual(2, len(payload["results"]))
            self.assertEqual("", stderr.getvalue())
        finally:
            __main__.load_config = original_loader
            __main__.install_signal_handlers = original_install
            if original_runners is not None:
                __main__._build_runtime_runners = original_runners

    def test_main_run_supports_orderbook(self):
        original_loader = __main__.load_config
        original_install = __main__.install_signal_handlers
        original_orderbook_runner = getattr(__main__, "_run_orderbook_collectors", None)
        try:
            __main__.load_config = lambda: type(
                "Config",
                (),
                {
                    "crypto_kline": type("Section", (), {"enabled": False})(),
                    "crypto_metrics": type("Section", (), {"enabled": False})(),
                    "crypto_orderbook": type("Section", (), {"enabled": True})(),
                    "equity": type("Section", (), {"enabled": False})(),
                    "fund_cn": type("Section", (), {"enabled": False})(),
                    "news": type("Section", (), {"enabled": False})(),
                    "to_public_dict": lambda self: {"ok": True},
                },
            )()
            __main__.install_signal_handlers = lambda state: None
            __main__._run_orderbook_collectors = lambda cfg, state=None, once=False: {
                "collector": "orderbook",
                "status": "skipped",
                "reason": "once_mode",
            }
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = __main__.main(["--run", "--once", "--only", "orderbook"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual([], payload["unsupported_collectors"])
            self.assertEqual(["orderbook"], payload["runnable_collectors"])
            self.assertEqual("orderbook", payload["results"][0]["collector"])
            self.assertEqual("", stderr.getvalue())
        finally:
            __main__.load_config = original_loader
            __main__.install_signal_handlers = original_install
            if original_orderbook_runner is None:
                delattr(__main__, "_run_orderbook_collectors")
            else:
                __main__._run_orderbook_collectors = original_orderbook_runner

    def test_run_fund_collectors_supports_once_mode(self):
        fund_module = sys.modules.get("src.collectors.fund")
        if fund_module is None:
            import src.collectors.fund as fund_module

        original_etf = getattr(fund_module, "ETFFundCollector", None)
        original_offmarket = getattr(fund_module, "OffMarketFundCollector", None)
        calls = []

        class _FakeEtfCollector(object):
            def __init__(self, config=None, writer=None):
                self.config = config
                self._writer = writer

            def run_once(self, batch_id=None, writer=None):
                calls.append("etf")
                return 2

            def close(self):
                calls.append("etf_close")

        class _FakeOffmarketCollector(object):
            def __init__(self, config=None, writer=None):
                self.config = config
                self._writer = writer

            def run_once(self, batch_id=None, writer=None):
                calls.append("offmarket")
                return 1

            def close(self):
                calls.append("offmarket_close")

        try:
            fund_module.ETFFundCollector = _FakeEtfCollector
            fund_module.OffMarketFundCollector = _FakeOffmarketCollector
            config = type(
                "Config",
                (),
                {
                    "runtime": type("Runtime", (), {"http_proxy": ""})(),
                    "fund_cn": type(
                        "Section",
                        (),
                        {
                            "enabled": True,
                            "interval_seconds": 60,
                            "etf_symbols": ["510300"],
                            "offmarket_codes": ["024389"],
                        },
                    )(),
                },
            )()

            result = __main__._run_fund_collectors(config, state=__main__.RuntimeState(), once=True)

            self.assertEqual("fund_cn", result["collector"])
            self.assertEqual("once", result["mode"])
            # Persistence is now timescaledb (schema gate opened)
            self.assertEqual("timescaledb", result["persistence"])
            self.assertIn("batch_id", result)
            self.assertEqual(
                [
                    {"component": "etf", "fetched": 2},
                    {"component": "offmarket", "fetched": 1},
                ],
                result["components"],
            )
            self.assertIn("etf", calls)
            self.assertIn("offmarket", calls)
        finally:
            if original_etf is None:
                delattr(fund_module, "ETFFundCollector")
            else:
                fund_module.ETFFundCollector = original_etf
            if original_offmarket is None:
                delattr(fund_module, "OffMarketFundCollector")
            else:
                fund_module.OffMarketFundCollector = original_offmarket

    def test_main_run_supports_fund_cn(self):
        original_loader = __main__.load_config
        original_install = __main__.install_signal_handlers
        original_fund_runner = getattr(__main__, "_run_fund_collectors", None)
        try:
            __main__.load_config = lambda: type(
                "Config",
                (),
                {
                    "crypto_kline": type("Section", (), {"enabled": False})(),
                    "crypto_metrics": type("Section", (), {"enabled": False})(),
                    "crypto_orderbook": type("Section", (), {"enabled": False})(),
                    "equity": type("Section", (), {"enabled": False})(),
                    "fund_cn": type("Section", (), {"enabled": False})(),
                    "news": type("Section", (), {"enabled": False})(),
                    "to_public_dict": lambda self: {"ok": True},
                },
            )()
            __main__.install_signal_handlers = lambda state: None
            __main__._run_fund_collectors = lambda cfg, state=None, once=False: {
                "collector": "fund_cn",
                "mode": "once",
                "components": [{"component": "etf", "fetched": 1}],
                "totals": [{"component": "etf", "fetched": 1}],
                "persistence": "none",
                "note": "schema_gate_no_fund_tables",
            }
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = __main__.main(["--run", "--once", "--only", "fund_cn"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual([], payload["unsupported_collectors"])
            self.assertEqual(["fund_cn"], payload["runnable_collectors"])
            self.assertEqual("fund_cn", payload["results"][0]["collector"])
            self.assertEqual("none", payload["results"][0]["persistence"])
            self.assertEqual("", stderr.getvalue())
        finally:
            __main__.load_config = original_loader
            __main__.install_signal_handlers = original_install
            if original_fund_runner is None:
                delattr(__main__, "_run_fund_collectors")
            else:
                __main__._run_fund_collectors = original_fund_runner

    def test_run_fund_collectors_returns_skipped_when_disabled(self):
        config = type(
            "Config",
            (),
            {
                "fund_cn": type(
                    "Section",
                    (),
                    {
                        "enabled": False,
                        "interval_seconds": 60,
                        "etf_symbols": ["510300"],
                        "offmarket_codes": ["024389"],
                    },
                )(),
            },
        )()

        result = __main__._run_fund_collectors(config, state=__main__.RuntimeState(), once=True)

        self.assertEqual({"collector": "fund_cn", "status": "skipped", "reason": "disabled_by_config"}, result)

    def test_run_fund_collectors_returns_skipped_when_symbols_are_missing(self):
        config = type(
            "Config",
            (),
            {
                "fund_cn": type(
                    "Section",
                    (),
                    {
                        "enabled": True,
                        "interval_seconds": 60,
                        "etf_symbols": [],
                        "offmarket_codes": [],
                    },
                )(),
            },
        )()

        result = __main__._run_fund_collectors(config, state=__main__.RuntimeState(), once=True)

        self.assertEqual({"collector": "fund_cn", "status": "skipped", "reason": "no_symbols_configured"}, result)

    def test_main_run_returns_non_zero_when_collector_fails(self):
        original_loader = __main__.load_config
        original_install = __main__.install_signal_handlers
        original_runners = getattr(__main__, "_build_runtime_runners", None)
        try:
            __main__.load_config = lambda: type(
                "Config",
                (),
                {
                    "crypto_kline": type("Section", (), {"enabled": True})(),
                    "crypto_metrics": type("Section", (), {"enabled": False})(),
                    "crypto_orderbook": type("Section", (), {"enabled": False})(),
                    "equity": type("Section", (), {"enabled": False})(),
                    "fund_cn": type("Section", (), {"enabled": False})(),
                    "news": type("Section", (), {"enabled": False})(),
                    "to_public_dict": lambda self: {"ok": True},
                },
            )()
            __main__.install_signal_handlers = lambda state: None

            def _boom():
                raise RuntimeError("boom")

            __main__._build_runtime_runners = lambda cfg, state=None, once=False: {"crypto": _boom}
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = __main__.main(["--run", "--once", "--only", "crypto"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("crypto", payload["failed_collectors"][0]["collector"])
            self.assertIn("boom", payload["failed_collectors"][0]["error"])
            self.assertIn("failed", stderr.getvalue())
        finally:
            __main__.load_config = original_loader
            __main__.install_signal_handlers = original_install
            if original_runners is not None:
                __main__._build_runtime_runners = original_runners


if __name__ == "__main__":
    unittest.main()
