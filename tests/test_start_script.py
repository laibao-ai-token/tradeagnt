import json
import os
import subprocess
import unittest


REPO_ROOT = "/home/tradecat"
START_SCRIPT = REPO_ROOT + "/scripts/start.sh"


class StartScriptTests(unittest.TestCase):
    def _run(self, *args, **env_overrides):
        env = os.environ.copy()
        env.update(env_overrides)
        return subprocess.run(
            ["bash", START_SCRIPT] + list(args),
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

    def test_help_mentions_collector_commands(self):
        result = self._run("unknown-command")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("start-collector", result.stdout)
        self.assertIn("status-collector", result.stdout)

    def test_default_core_service_list_uses_collector(self):
        with open(START_SCRIPT, "r") as fh:
            script_text = fh.read()

        self.assertIn("SERVICES=(collector-service signal-service trading-service)", script_text)
        self.assertNotIn("SERVICES=(data-service signal-service trading-service)", script_text)

    def test_start_collector_delegates_selectors(self):
        result = self._run(
            "start-collector",
            "--only=news",
            COLLECTOR_NEWS_ENABLED="0",
        )

        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual(["news"], payload["enabled_collectors"])
        self.assertEqual("run", payload["mode"])
        self.assertEqual(["news"], payload["runnable_collectors"])

    def test_status_collector_prints_enabled_collectors(self):
        result = self._run(
            "status-collector",
            COLLECTOR_NEWS_ENABLED="1",
            COLLECTOR_CRYPTO_ORDERBOOK_ENABLED="1",
        )

        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual(["orderbook", "news"], payload["enabled_collectors"])
        self.assertEqual(2, payload["collector_count"])

    def test_default_status_uses_collector_service_scope(self):
        result = self._run("status")

        self.assertEqual(0, result.returncode)
        self.assertIn("[collector-service]", result.stdout)
        self.assertIn("[signal-service]", result.stdout)
        self.assertIn("[trading-service]", result.stdout)
        self.assertNotIn("[data-service]", result.stdout)

    def test_default_stop_uses_collector_service_scope(self):
        result = self._run("stop")

        self.assertEqual(0, result.returncode)
        self.assertIn("[collector-service]", result.stdout)
        self.assertIn("[signal-service]", result.stdout)
        self.assertIn("[trading-service]", result.stdout)
        self.assertNotIn("[data-service]", result.stdout)


if __name__ == "__main__":
    unittest.main()
