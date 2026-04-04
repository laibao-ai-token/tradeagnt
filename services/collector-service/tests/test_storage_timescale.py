import unittest

from src.storage import timescale as storage_module

from tests.storage_fakes import FakePool


class TimescaleStorageTests(unittest.TestCase):
    def setUp(self):
        if hasattr(storage_module, "reset_shared_pool"):
            storage_module.reset_shared_pool()
        FakePool.reset()

    def test_default_database_url_reuses_shared_pool(self):
        storage_a = storage_module.TimescaleStorage(
            db_url="postgresql://default/db",
            default_db_url="postgresql://default/db",
            pool_factory=FakePool,
        )
        storage_b = storage_module.TimescaleStorage(
            db_url="postgresql://default/db",
            default_db_url="postgresql://default/db",
            pool_factory=FakePool,
        )

        self.assertIs(storage_a.pool, storage_b.pool)
        self.assertEqual(1, len(FakePool.created))

    def test_non_default_database_url_uses_private_pool_and_close_releases_it(self):
        storage = storage_module.TimescaleStorage(
            db_url="postgresql://private/db",
            default_db_url="postgresql://default/db",
            pool_factory=FakePool,
        )

        pool = storage.pool
        self.assertEqual(1, len(FakePool.created))
        self.assertIs(pool, storage.pool)

        storage.close()

        self.assertTrue(pool.closed)
        self.assertIsNone(storage._pool)


if __name__ == "__main__":
    unittest.main()
