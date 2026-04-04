import os
import unittest
from unittest import mock

from src.core.fetcher import BaseFetcher
from src.core.key_manager import KeyManager, get_key_manager
from src.core.registry import ProviderRegistry, register_fetcher


class DummyQuery(object):
    def __init__(self, symbol):
        self.symbol = symbol


class DummyData(object):
    def __init__(self, symbol):
        self.symbol = symbol

    def __eq__(self, other):
        return isinstance(other, DummyData) and self.symbol == other.symbol


class TestProviderRegistry(unittest.TestCase):
    def setUp(self):
        ProviderRegistry._fetchers.clear()

    def tearDown(self):
        ProviderRegistry._fetchers.clear()

    def test_register_fetcher_decorator_registers_fetcher_class(self):
        @register_fetcher("dummy", "candle")
        class DummyFetcher(BaseFetcher):
            def transform_query(self, params):
                return DummyQuery(**params)

            async def extract(self, query):
                return [{"symbol": query.symbol}]

            def transform_data(self, raw):
                return [DummyData(**row) for row in raw]

        self.assertIs(DummyFetcher, ProviderRegistry.get("dummy", "candle"))
        self.assertEqual(["dummy"], ProviderRegistry.list_providers())
        self.assertEqual(["candle"], ProviderRegistry.list_data_types("dummy"))
        self.assertEqual("dummy", DummyFetcher.provider)

    def test_base_fetcher_runs_full_pipeline(self):
        @register_fetcher("dummy", "candle")
        class DummyFetcher(BaseFetcher):
            def transform_query(self, params):
                return DummyQuery(**params)

            async def extract(self, query):
                return [{"symbol": query.symbol}]

            def transform_data(self, raw):
                return [DummyData(**row) for row in raw]

        fetcher = DummyFetcher()

        data = fetcher.fetch_sync(symbol="BTCUSDT")

        self.assertEqual([DummyData(symbol="BTCUSDT")], data)


class TestKeyManager(unittest.TestCase):
    def tearDown(self):
        from src.core import key_manager as key_manager_module

        key_manager_module._managers.clear()

    def test_round_robin_and_cooldown_exclude_unhealthy_key(self):
        with mock.patch.dict(os.environ, {"TEST_PROVIDER_KEYS": "key-1,key-2"}, clear=False):
            with mock.patch("src.core.key_manager.time.time", return_value=100.0):
                manager = KeyManager("TEST_PROVIDER_KEYS", cooldown_seconds=30)
                first = manager.get_key()
                second = manager.get_key()

                manager.report_error(first)
                manager.report_error(first)
                manager.report_error(first)

                third = manager.get_key()
                stats = manager.stats()

        self.assertEqual("key-1", first)
        self.assertEqual("key-2", second)
        self.assertEqual("key-2", third)
        self.assertEqual(2, stats["total"])
        self.assertEqual(1, stats["available"])

    def test_get_key_manager_returns_singleton_per_env_var(self):
        with mock.patch.dict(os.environ, {"TEST_PROVIDER_KEYS": "key-1,key-2"}, clear=False):
            first = get_key_manager("TEST_PROVIDER_KEYS")
            second = get_key_manager("TEST_PROVIDER_KEYS")
            other = get_key_manager("OTHER_PROVIDER_KEYS")

        self.assertIs(first, second)
        self.assertIsNot(first, other)


if __name__ == "__main__":
    unittest.main()
