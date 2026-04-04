import unittest

from src.config import load_config


class TestCollectorConfig(unittest.TestCase):
    def test_new_keys_override_legacy_keys(self):
        cfg = load_config(
            {
                "COLLECTOR_DATABASE_URL": "postgresql://new/newdb",
                "MARKETS_SERVICE_DATABASE_URL": "postgresql://legacy/markets",
                "DATABASE_URL": "postgresql://legacy/global",
                "COLLECTOR_BACKFILL_MODE": "none",
                "BACKFILL_MODE": "days",
                "COLLECTOR_NEWS_FEEDS": "feed-a,feed-b,feed-a",
                "NEWS_RSS_FEEDS": "legacy-feed",
                "COLLECTOR_CRYPTO_ORDERBOOK_TICK_INTERVAL": "3",
                "ORDER_BOOK_TICK_INTERVAL": "1",
                "COLLECTOR_CRYPTO_KLINE_ENABLED": "true",
            }
        )

        self.assertEqual("postgresql://new/newdb", cfg.database.database_url)
        self.assertEqual("none", cfg.runtime.backfill_mode)
        self.assertEqual(["feed-a", "feed-b"], cfg.news.feeds)
        self.assertEqual(3, cfg.crypto_orderbook.tick_interval)
        self.assertTrue(cfg.crypto_kline.enabled)

    def test_legacy_fallbacks_are_used_when_new_keys_are_missing(self):
        cfg = load_config(
            {
                "MARKETS_SERVICE_DATABASE_URL": "postgresql://legacy/markets",
                "CRYPTO_WRITE_MODE": "legacy",
                "BACKFILL_MODE": "full",
                "BACKFILL_DAYS": "14",
                "BACKFILL_START_DATE": "2020-01-01",
                "RATE_LIMIT_PER_MINUTE": "900",
                "BINANCE_WS_GAP_INTERVAL": "120",
                "NEWS_RSS_FEEDS": "rss-a,rss-b",
                "NEWS_RSS_TIMEOUT_SECONDS": "30",
                "ORDER_BOOK_TICK_INTERVAL": "2",
                "ORDER_BOOK_FULL_INTERVAL": "8",
                "ORDER_BOOK_DEPTH": "50",
                "ORDER_BOOK_RETENTION_DAYS": "7",
            }
        )

        self.assertEqual("postgresql://legacy/markets", cfg.database.database_url)
        self.assertEqual("legacy", cfg.database.crypto_write_mode)
        self.assertEqual("all", cfg.runtime.backfill_mode)
        self.assertEqual(14, cfg.runtime.backfill_days)
        self.assertEqual("2020-01-01", cfg.runtime.backfill_start_date)
        self.assertEqual(900, cfg.runtime.rate_limit_per_minute)
        self.assertEqual(120, cfg.runtime.gap_check_interval)
        self.assertEqual(["rss-a", "rss-b"], cfg.news.feeds)
        self.assertEqual(30, cfg.news.timeout_seconds)
        self.assertEqual(2, cfg.crypto_orderbook.tick_interval)
        self.assertEqual(8, cfg.crypto_orderbook.full_interval)
        self.assertEqual(50, cfg.crypto_orderbook.depth)
        self.assertEqual(7, cfg.crypto_orderbook.retention_days)

    def test_invalid_backfill_mode_raises(self):
        with self.assertRaises(ValueError):
            load_config({"COLLECTOR_BACKFILL_MODE": "broken"})

    def test_invalid_crypto_write_mode_raises(self):
        with self.assertRaises(ValueError):
            load_config({"COLLECTOR_CRYPTO_WRITE_MODE": "broken"})

    def test_public_dict_redacts_database_url(self):
        cfg = load_config({"COLLECTOR_DATABASE_URL": "postgresql://secret/db"})

        public = cfg.to_public_dict()

        self.assertEqual("<redacted>", public["database"]["database_url"])
        self.assertNotEqual("postgresql://secret/db", public["database"]["database_url"])

    def test_crypto_kline_runtime_keys_support_new_and_legacy_fallbacks(self):
        cfg = load_config(
            {
                "COLLECTOR_CRYPTO_KLINE_PROVIDER": "gate_spot_poll",
                "DATA_CANDLE_PROVIDER": "binance_futures_ws",
                "COLLECTOR_CRYPTO_KLINE_WS_SOURCE": "collector_ws",
                "BINANCE_WS_SOURCE": "legacy_ws",
                "COLLECTOR_CRYPTO_KLINE_DB_EXCHANGE": "collector_um",
                "BINANCE_WS_DB_EXCHANGE": "legacy_um",
                "COLLECTOR_CRYPTO_KLINE_CCXT_EXCHANGE": "binanceusdm",
                "BINANCE_WS_CCXT_EXCHANGE": "binance",
                "COLLECTOR_CRYPTO_KLINE_GATE_POLL_INTERVAL_SECONDS": "15",
                "GATE_SPOT_POLL_INTERVAL": "9",
                "COLLECTOR_CRYPTO_KLINE_GATE_TIMEOUT_SECONDS": "12",
                "GATE_SPOT_TIMEOUT": "7",
                "COLLECTOR_CRYPTO_KLINE_GATE_WORKERS": "3",
                "GATE_SPOT_WORKERS": "2",
                "COLLECTOR_CRYPTO_KLINE_GATE_DB_EXCHANGE": "collector_gate",
                "GATE_SPOT_DB_EXCHANGE": "legacy_gate",
            }
        )

        self.assertEqual("gate_spot_poll", cfg.crypto_kline.provider)
        self.assertEqual("collector_ws", cfg.crypto_kline.ws_source)
        self.assertEqual("collector_um", cfg.crypto_kline.db_exchange)
        self.assertEqual("binanceusdm", cfg.crypto_kline.ccxt_exchange)
        self.assertEqual(15, cfg.crypto_kline.gate_poll_interval_seconds)
        self.assertEqual(12, cfg.crypto_kline.gate_timeout_seconds)
        self.assertEqual(3, cfg.crypto_kline.gate_workers)
        self.assertEqual("collector_gate", cfg.crypto_kline.gate_db_exchange)

    def test_equity_runtime_keys_support_provider_switches(self):
        cfg = load_config(
            {
                "COLLECTOR_EQUITY_ENABLED": "true",
                "COLLECTOR_EQUITY_MARKETS": "us,hk",
                "COLLECTOR_EQUITY_POLL_INTERVAL_SECONDS": "45",
                "COLLECTOR_EQUITY_INTERVAL": "5m",
                "COLLECTOR_EQUITY_LIMIT": "3",
                "COLLECTOR_EQUITY_US_PROVIDER": "yfinance",
                "COLLECTOR_EQUITY_CN_PROVIDER": "akshare",
                "COLLECTOR_EQUITY_HK_PROVIDER": "tencent",
                "COLLECTOR_EQUITY_US_SYMBOLS": "AAPL,NVDA",
                "COLLECTOR_EQUITY_HK_SYMBOLS": "00700.HK",
            }
        )

        self.assertTrue(cfg.equity.enabled)
        self.assertEqual(["us", "hk"], cfg.equity.markets)
        self.assertEqual(45, cfg.equity.poll_interval_seconds)
        self.assertEqual("5m", cfg.equity.interval)
        self.assertEqual(3, cfg.equity.limit)
        self.assertEqual("yfinance", cfg.equity.us_provider)
        self.assertEqual("akshare", cfg.equity.cn_provider)
        self.assertEqual("tencent", cfg.equity.hk_provider)
        self.assertEqual(["AAPL", "NVDA"], cfg.equity.us_symbols)
        self.assertEqual(["00700.HK"], cfg.equity.hk_symbols)

    def test_fund_runtime_keys_support_symbol_lists(self):
        cfg = load_config(
            {
                "COLLECTOR_FUND_CN_ENABLED": "true",
                "COLLECTOR_FUND_CN_INTERVAL": "75",
                "COLLECTOR_FUND_CN_ETF_SYMBOLS": "510300,SZ159915",
                "COLLECTOR_FUND_CN_OFFMARKET_CODES": "024389,040046",
            }
        )

        self.assertTrue(cfg.fund_cn.enabled)
        self.assertEqual(75, cfg.fund_cn.interval_seconds)
        self.assertEqual(["510300", "SZ159915"], cfg.fund_cn.etf_symbols)
        self.assertEqual(["024389", "040046"], cfg.fund_cn.offmarket_codes)


if __name__ == "__main__":
    unittest.main()
