"""Tests for config/pipeline profile loading."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from tradecat.core.pipeline.profile import (
    apply_pipeline_profile,
    bootstrap_pipeline_profile,
    load_pipeline_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class PipelineProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_profile = os.environ.pop("TRADECAT_PIPELINE_PROFILE", None)

    def tearDown(self) -> None:
        if self._saved_profile is None:
            os.environ.pop("TRADECAT_PIPELINE_PROFILE", None)
        else:
            os.environ["TRADECAT_PIPELINE_PROFILE"] = self._saved_profile

    def test_load_tui_dual(self) -> None:
        profile = load_pipeline_profile("tui_dual", repo_root=REPO_ROOT)
        self.assertEqual(profile.name, "tui_dual")
        self.assertEqual(profile.strategy_paths[0], "current/fast_1m.yaml")
        self.assertEqual(profile.extra_strategy, "current/us_fast_5m.yaml")
        self.assertEqual(profile.paper_markets, "all")

    def test_apply_sets_env_when_unset(self) -> None:
        profile = load_pipeline_profile("tui_dual", repo_root=REPO_ROOT)
        keys = [
            "TUI_SIGNAL_STRATEGY",
            "TUI_SIGNAL_STRATEGY_EXTRA",
            "PAPER_AUTO_MARKET",
            "TUI_SIGNAL_POLL_INTERVAL_S",
        ]
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            apply_pipeline_profile(profile, only_if_unset=True)
            self.assertEqual(os.environ["TUI_SIGNAL_STRATEGY"], "current/fast_1m.yaml")
            self.assertEqual(os.environ["TUI_SIGNAL_STRATEGY_EXTRA"], "current/us_fast_5m.yaml")
            self.assertEqual(os.environ["PAPER_AUTO_MARKET"], "all")
            self.assertEqual(os.environ["TUI_SIGNAL_POLL_INTERVAL_S"], "60")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_bootstrap_reads_env_name(self) -> None:
        saved = os.environ.get("TRADECAT_PIPELINE_PROFILE")
        os.environ["TRADECAT_PIPELINE_PROFILE"] = "daemon_crypto"
        try:
            profile = bootstrap_pipeline_profile(repo_root=REPO_ROOT, only_if_unset=False)
            assert profile is not None
            self.assertEqual(profile.name, "daemon_crypto")
            self.assertEqual(os.environ["TUI_SIGNAL_STRATEGY"], "current/fast_1m.yaml")
            self.assertEqual(os.environ["PAPER_AUTO_MARKET"], "crypto")
        finally:
            if saved is None:
                os.environ.pop("TRADECAT_PIPELINE_PROFILE", None)
            else:
                os.environ["TRADECAT_PIPELINE_PROFILE"] = saved


if __name__ == "__main__":
    unittest.main()
