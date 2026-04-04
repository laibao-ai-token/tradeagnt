import unittest


REPO_ROOT = "/home/tradecat"


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class ScriptAlignmentTests(unittest.TestCase):
    def test_verify_script_checks_collector_sources(self):
        script_text = _read(REPO_ROOT + "/scripts/verify.sh")

        self.assertIn("services/collector-service/src", script_text)
        self.assertNotIn("services/data-service/src", script_text)
        self.assertNotIn("services-preview/markets-service/src", script_text)

    def test_check_env_checks_collector_runtime_paths(self):
        script_text = _read(REPO_ROOT + "/scripts/check_env.sh")

        self.assertIn("collector-service", script_text)
        self.assertNotIn("services/data-service/logs", script_text)
        self.assertNotIn("services-preview/markets-service/logs", script_text)

    def test_install_script_targets_collector_service(self):
        script_text = _read(REPO_ROOT + "/scripts/install.sh")

        self.assertIn("collector-service", script_text)
        self.assertNotIn("services/data-service", script_text)

    def test_tui_start_script_no_longer_depends_on_data_service_or_markets_service(self):
        script_text = _read(REPO_ROOT + "/services-preview/tui-service/scripts/start.sh")

        self.assertIn("collector-service", script_text)
        self.assertNotIn("services/data-service", script_text)
        self.assertNotIn("services-preview/markets-service", script_text)


if __name__ == "__main__":
    unittest.main()
