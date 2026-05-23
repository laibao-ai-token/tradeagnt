import json
import os
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPO_ROOT / "scripts" / "start.sh"


class StartScriptTests(unittest.TestCase):
    def _run(self, *args, **env_overrides):
        env = os.environ.copy()
        env.update(env_overrides)
        return subprocess.run(
            ["bash", str(START_SCRIPT)] + list(args),
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

    def test_help_mentions_collector_commands(self) -> None:
        result = self._run("unknown-command")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("start-collector", result.stdout)
        self.assertIn("status-collector", result.stdout)

    def test_start_collector_on_demand_json(self) -> None:
        result = self._run("start-collector", "--only=news", COLLECTOR_NEWS_ENABLED="0")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("on_demand", payload["data_mode"])
        self.assertEqual(["news"], payload["enabled_collectors"])
        self.assertEqual("run", payload["mode"])

    def test_status_collector_on_demand_json(self) -> None:
        result = self._run(
            "status-collector",
            COLLECTOR_NEWS_ENABLED="1",
            COLLECTOR_CRYPTO_ORDERBOOK_ENABLED="1",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(["news", "orderbook"], payload["enabled_collectors"])
        self.assertEqual(2, payload["collector_count"])

    def test_status_all_skips_missing_legacy_services(self) -> None:
        result = self._run("status")
        self.assertEqual(0, result.returncode)
        self.assertIn("[collector-service]", result.stdout)


if __name__ == "__main__":
    unittest.main()
