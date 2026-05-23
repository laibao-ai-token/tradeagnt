import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ScriptAlignmentTests(unittest.TestCase):
    def test_verify_script_checks_monolith_sources(self) -> None:
        script_text = _read(REPO_ROOT / "scripts" / "verify.sh")
        self.assertIn("src/tradecat", script_text)

    def test_start_sh_has_on_demand_collector_fallback(self) -> None:
        script_text = _read(REPO_ROOT / "scripts" / "start.sh")
        self.assertIn("collector_on_demand_cli", script_text)
        self.assertIn("on_demand", _read(REPO_ROOT / "docs" / "pipeline" / "DATA_COLLECTION.md"))

    def test_install_script_exists(self) -> None:
        self.assertTrue((REPO_ROOT / "scripts" / "install.sh").is_file())

    def test_tui_cli_does_not_require_collector_by_default(self) -> None:
        script_text = _read(REPO_ROOT / "src" / "tradecat" / "cli" / "tui.py")
        self.assertIn("TUI_AUTO_START_COLLECTOR", script_text)


if __name__ == "__main__":
    unittest.main()
