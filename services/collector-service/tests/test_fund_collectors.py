import unittest

from src.adapters.eastmoney import parse_fundgz_jsonp
from src.adapters.tencent import fetch_tencent_cn_quotes, parse_tencent_cn_quote_line
from src.collectors.fund.etf import ETFFundCollector
from src.collectors.fund.offmarket import OffMarketFundCollector
from src.collectors.fund.symbols import cn_fund_exchange_candidates, normalize_cn_fund_symbol


def _build_config():
    return type(
        "Config",
        (),
        {
            "fund_cn": type(
                "FundCN",
                (),
                {
                    "enabled": True,
                    "interval_seconds": 60,
                    "etf_symbols": ["510300", "SZ159915"],
                    "offmarket_codes": ["024389"],
                },
            )(),
            "runtime": type("Runtime", (), {"http_proxy": ""})(),
        },
    )()


class FundCollectorTests(unittest.TestCase):
    def test_parse_tencent_cn_quote_line_returns_normalized_quote(self):
        line = (
            'v_sh510300="1~300ETF~510300~3.100~3.000~3.000~10000~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
            '2026-03-31 14:32:00~0~0~3.150~3.050~31.00万~100~31.00~";'
        )

        quote = parse_tencent_cn_quote_line(line)

        self.assertIsNotNone(quote)
        self.assertEqual("SH510300", quote["symbol"])
        self.assertAlmostEqual(3.1, quote["price"], places=6)
        self.assertAlmostEqual(310000.0, quote["amount"], places=6)
        self.assertEqual("tencent", quote["source"])
        self.assertEqual("CNY", quote["currency"])

    def test_normalize_cn_fund_symbol_and_exchange_candidates(self):
        self.assertEqual("SH510300", normalize_cn_fund_symbol("510300.SH"))
        self.assertEqual("024389", normalize_cn_fund_symbol("024389"))
        self.assertEqual("", normalize_cn_fund_symbol("abc"))
        self.assertEqual(["SH510300"], cn_fund_exchange_candidates("510300"))
        self.assertEqual(["SZ159915"], cn_fund_exchange_candidates("SZ159915"))
        self.assertEqual([], cn_fund_exchange_candidates("024389"))

    def test_parse_fundgz_jsonp_returns_normalized_quote(self):
        payload = (
            'jsonpgz({"fundcode":"024389","name":"中航智选领航混合发起C",'
            '"jzrq":"2026-02-18","dwjz":"1.1234","gsz":"1.1301","gszzl":"0.60",'
            '"gztime":"2026-02-19 14:32"});'
        )

        quote = parse_fundgz_jsonp(payload)

        self.assertIsNotNone(quote)
        self.assertEqual("024389", quote["symbol"])
        self.assertEqual("CNY", quote["currency"])
        self.assertAlmostEqual(1.1301, quote["price"], places=6)
        self.assertAlmostEqual(1.1234, quote["prev_close"], places=6)
        self.assertEqual("fundgz", quote["source"])

    def test_etf_fund_collector_fetches_tencent_quotes(self):
        calls = []

        def _fetch_quotes(symbols, timeout_s=0.0, proxy=""):
            calls.append({"symbols": list(symbols), "timeout_s": timeout_s, "proxy": proxy})
            return {
                "SH510300": {
                    "symbol": "SH510300",
                    "name": "300ETF",
                    "price": 3.1,
                    "prev_close": 3.0,
                    "open": 3.0,
                    "high": 3.1,
                    "low": 3.0,
                    "volume": 100.0,
                    "amount": 310.0,
                    "ts": "2026-03-31 14:32:00",
                    "source": "tencent",
                    "currency": "CNY",
                },
                "SZ159915": {
                    "symbol": "SZ159915",
                    "name": "创业板ETF",
                    "price": 2.2,
                    "prev_close": 2.1,
                    "open": 2.1,
                    "high": 2.2,
                    "low": 2.1,
                    "volume": 88.0,
                    "amount": 193.6,
                    "ts": "2026-03-31 14:32:00",
                    "source": "tencent",
                    "currency": "CNY",
                },
            }

        collector = ETFFundCollector(config=_build_config(), fetch_quotes=_fetch_quotes)

        rows = collector.collect()
        fetched = collector.run_once()

        self.assertEqual(2, len(rows))
        self.assertEqual(2, fetched)
        self.assertEqual(["SH510300", "SZ159915"], calls[0]["symbols"])
        self.assertEqual("SH510300", rows[0]["symbol"])
        self.assertEqual("SZ159915", rows[1]["symbol"])

    def test_fetch_tencent_cn_quotes_parses_batched_payload(self):
        payload = (
            'v_sh510300="1~300ETF~510300~3.100~3.000~3.000~10000~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
            '2026-03-31 14:32:00~0~0~3.150~3.050~31.00万~100~31.00~";\n'
            'v_sz159915="1~创业板ETF~159915~2.200~2.100~2.100~8800~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
            '2026-03-31 14:32:00~0~0~2.250~2.050~19.36万~88~19.36~";'
        )

        quotes = fetch_tencent_cn_quotes(
            ["510300.SH", "SZ159915"],
            timeout_s=1.0,
            fetch_text=lambda url, timeout_s, proxy="": payload,
        )

        self.assertEqual(["SH510300", "SZ159915"], sorted(quotes.keys()))
        self.assertAlmostEqual(3.1, quotes["SH510300"]["price"], places=6)
        self.assertAlmostEqual(2.2, quotes["SZ159915"]["price"], places=6)

    def test_etf_fund_collector_returns_empty_when_batch_fetch_fails(self):
        collector = ETFFundCollector(
            config=_build_config(),
            fetch_quotes=lambda symbols, timeout_s=0.0, proxy="": (_ for _ in ()).throw(RuntimeError("down")),
        )

        rows = collector.collect(symbols=["510300"])

        self.assertEqual([], rows)

    def test_offmarket_fund_collector_fetches_eastmoney_quotes(self):
        calls = []

        def _fetch_quote(code, timeout_s=0.0, proxy=""):
            calls.append({"code": code, "timeout_s": timeout_s, "proxy": proxy})
            return {
                "symbol": code,
                "name": "中航智选领航混合发起C",
                "price": 1.23,
                "prev_close": 1.22,
                "open": 1.22,
                "high": 1.23,
                "low": 1.23,
                "volume": 0.0,
                "amount": 0.0,
                "ts": "2026-03-31 14:32:00",
                "source": "fundgz",
                "currency": "CNY",
            }

        collector = OffMarketFundCollector(config=_build_config(), fetch_quote=_fetch_quote)

        rows = collector.collect()
        fetched = collector.run_once()

        self.assertEqual(1, len(rows))
        self.assertEqual(1, fetched)
        self.assertEqual("024389", calls[0]["code"])
        self.assertEqual("024389", rows[0]["symbol"])

    def test_offmarket_fund_collector_skips_failed_code_and_continues(self):
        calls = []

        def _fetch_quote(code, timeout_s=0.0, proxy=""):
            calls.append(code)
            if code == "024389":
                raise RuntimeError("upstream down")
            return {
                "symbol": code,
                "name": code,
                "price": 1.0,
                "prev_close": 1.0,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "volume": 0.0,
                "amount": 0.0,
                "ts": "2026-03-31 14:32:00",
                "source": "fundgz",
                "currency": "CNY",
            }

        collector = OffMarketFundCollector(config=_build_config(), fetch_quote=_fetch_quote)

        rows = collector.collect(codes=["024389", "040046"])

        self.assertEqual(["024389", "040046"], calls)
        self.assertEqual(1, len(rows))
        self.assertEqual("040046", rows[0]["symbol"])


if __name__ == "__main__":
    unittest.main()
