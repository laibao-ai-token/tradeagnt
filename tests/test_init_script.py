import unittest


REPO_ROOT = "/home/tradecat"
INIT_SCRIPT = REPO_ROOT + "/scripts/init.sh"


class InitScriptTests(unittest.TestCase):
    def test_default_core_service_list_uses_collector(self):
        with open(INIT_SCRIPT, "r") as fh:
            script_text = fh.read()

        self.assertIn('CORE_SERVICES=(collector-service trading-service signal-service)', script_text)
        self.assertNotIn('CORE_SERVICES=(data-service trading-service signal-service)', script_text)

    def test_all_mode_only_keeps_tui_as_preview_service(self):
        with open(INIT_SCRIPT, "r") as fh:
            script_text = fh.read()

        self.assertIn('PREVIEW_SERVICES=(tui-service)', script_text)
        self.assertNotIn('PREVIEW_SERVICES=(markets-service tui-service)', script_text)


if __name__ == "__main__":
    unittest.main()
