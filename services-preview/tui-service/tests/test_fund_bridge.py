from __future__ import annotations

from collections import deque
from unittest import TestCase
from unittest.mock import patch

from src.fund_bridge import DirectFundBridge, seed_curve_from_daily_candles
from src.micro import Candle
from src.quote import Quote


class TestFundBridge(TestCase):
    def test_fetch_quote_rows_preserves_requested_symbol(self) -> None:
        bridge = DirectFundBridge()
        now_ts = 12345.0

        quotes = {
            "510300": Quote(
                symbol="SH510300",
                name="CSI300",
                price=3.14,
                prev_close=3.15,
                open=3.12,
                high=3.16,
                low=3.10,
                currency="CNY",
                volume=1_000_000.0,
                amount=3_140_000.0,
                ts="2026-03-29 15:00:00",
                source="tencent",
            ),
            "SZ159915": Quote(
                symbol="SZ159915",
                name="STAR",
                price=1.23,
                prev_close=1.25,
                open=1.22,
                high=1.26,
                low=1.21,
                currency="CNY",
                volume=500_000.0,
                amount=615_000.0,
                ts="2026-03-29 15:00:00",
                source="tencent",
            ),
        }

        def fake_fetch_quotes(provider: str, market: str, symbols: list[str], timeout_s: float = 3.0):
            self.assertEqual("tencent", provider)
            self.assertEqual("cn_fund", market)
            self.assertEqual({"510300", "SZ159915"}, set(symbols))
            return {symbol: quotes[symbol] for symbol in symbols if symbol in quotes}

        with patch("src.fund_bridge.fetch_quotes", side_effect=fake_fetch_quotes):
            with patch("src.fund_bridge.time.time", return_value=now_ts):
                rows = bridge.fetch_quote_rows(["510300", "SZ159915", "bad"], now_ts=None)

        self.assertIn("510300", rows)
        self.assertEqual("510300", rows["510300"].request_symbol)
        self.assertEqual("SH510300", rows["510300"].quote_symbol)
        self.assertEqual(now_ts, rows["510300"].last_fetch_at)
        self.assertEqual(2, len(rows))

    def test_fetch_quote_rows_preserves_caller_symbol_form(self) -> None:
        bridge = DirectFundBridge()
        original = " 510300.Sh "
        trimmed = "510300.Sh"

        quote = Quote(
            symbol="SH510300",
            name="CSI300",
            price=3.14,
            prev_close=3.15,
            open=3.12,
            high=3.16,
            low=3.10,
            currency="CNY",
            volume=1_000_000.0,
            amount=3_140_000.0,
            ts="2026-03-29 15:00:00",
            source="tencent",
        )

        def fake_fetch_quotes(provider: str, market: str, symbols: list[str], timeout_s: float = 3.0):
            self.assertEqual(["SH510300"], symbols)
            return {"SH510300": quote}

        with patch("src.fund_bridge.fetch_quotes", side_effect=fake_fetch_quotes):
            rows = bridge.fetch_quote_rows([original], now_ts=0.0)

        self.assertIn(trimmed, rows)
        self.assertEqual(trimmed, rows[trimmed].request_symbol)
        self.assertEqual("SH510300", rows[trimmed].quote_symbol)
        self.assertEqual(0.0, rows[trimmed].last_fetch_at)

    def test_fetch_daily_candles_converts_curve_rows(self) -> None:
        bridge = DirectFundBridge()

        series = [
            (1700000000, 10.0, 11.0, 9.5, 10.5, 1000.0),
            (1700086400, 10.5, 11.5, 10.0, 11.0, 2000.0),
        ]

        with patch("src.fund_bridge.fetch_daily_curve_1d", return_value=series) as mocked:
            candles = bridge.fetch_daily_candles("510300", limit=3)
            mocked.assert_called_once()

        self.assertEqual(2, len(candles))
        self.assertEqual(series[0][0], candles[0].ts_open)
        self.assertAlmostEqual(series[0][5] * series[0][4], candles[0].notional_est, places=6)
        self.assertEqual([], bridge.fetch_daily_candles("invalid", limit=2))

    def test_seed_curve_from_daily_candles_replaces_buffer(self) -> None:
        curves: dict[str, deque[Candle]] = {
            "SH510300": deque([Candle(1, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)], maxlen=2)
        }
        input_candles = [
            Candle(100, 1.0, 1.2, 0.9, 1.1, 10.0, 11.0),
            Candle(200, 1.1, 1.3, 1.0, 1.2, 20.0, 24.0),
        ]

        result = seed_curve_from_daily_candles(curves, "SH510300", input_candles, max_points=2)

        self.assertTrue(result)
        self.assertEqual(2, len(curves["SH510300"]))
        self.assertEqual(input_candles[-1].ts_open, curves["SH510300"][-1].ts_open)

    def test_seed_curve_from_daily_candles_truncates_to_max_points(self) -> None:
        curves: dict[str, deque[Candle]] = {}
        input_candles = [
            Candle(100 + i * 100, 1.0, 1.1, 0.9, 1.05 + 0.01 * i, 10.0 + i, 11.0 + i)
            for i in range(4)
        ]

        result = seed_curve_from_daily_candles(curves, "510300", input_candles, max_points=2)

        self.assertTrue(result)
        normalized = "SH510300"
        self.assertEqual(2, len(curves[normalized]))
        self.assertEqual(input_candles[-2].ts_open, curves[normalized][0].ts_open)
        self.assertEqual(input_candles[-1].ts_open, curves[normalized][-1].ts_open)

    def test_fetch_daily_candles_filters_nonfinite_rows(self) -> None:
        bridge = DirectFundBridge()

        series = [
            (1700000000, float("nan"), 11.0, 10.0, 10.5, 1000.0),
            (1700086400, 10.5, float("inf"), 10.0, 11.0, 2000.0),
            (1700172800, 11.0, 11.5, float("-inf"), 11.2, 1500.0),
            (1700259200, 11.2, 11.6, 11.1, float("nan"), 1600.0),
            (1700345600, 11.4, 11.9, 11.3, 11.5, float("nan")),
            (1700432000, 11.5, 12.0, 11.4, 11.8, 2100.0),
        ]

        with patch("src.fund_bridge.fetch_daily_curve_1d", return_value=series):
            candles = bridge.fetch_daily_candles("510300", limit=10)

        self.assertEqual(1, len(candles))
        self.assertEqual(series[-1][0], candles[0].ts_open)
