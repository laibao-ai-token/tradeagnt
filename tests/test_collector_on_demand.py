"""Unit tests for on-demand collector stub."""

from __future__ import annotations

import os
import unittest

from scripts.lib.collector_on_demand import build_payload


class CollectorOnDemandTests(unittest.TestCase):
    def test_only_selector(self) -> None:
        payload = build_payload(["--only=news", "--run"])
        self.assertEqual(payload["enabled_collectors"], ["news"])
        self.assertEqual(payload["mode"], "run")

    def test_env_enabled_collectors(self) -> None:
        saved = {
            k: os.environ.pop(k, None)
            for k in ("COLLECTOR_NEWS_ENABLED", "COLLECTOR_CRYPTO_ORDERBOOK_ENABLED")
        }
        try:
            os.environ["COLLECTOR_NEWS_ENABLED"] = "1"
            os.environ["COLLECTOR_CRYPTO_ORDERBOOK_ENABLED"] = "1"
            payload = build_payload([])
            self.assertEqual(payload["enabled_collectors"], ["news", "orderbook"])
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
