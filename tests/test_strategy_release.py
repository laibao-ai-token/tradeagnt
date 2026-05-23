"""Tests for scripts/strategy_release.py bundle/snapshot."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "strategy_release.py"
V08_RELEASE = "20260523_v08_dual"
CURRENT_LINK = REPO_ROOT / "config" / "strategies" / "current"


class StrategyReleaseTests(unittest.TestCase):
    def tearDown(self) -> None:
        """Restore freeze release after tests that --activate."""
        target = REPO_ROOT / "config" / "strategies" / "releases" / V08_RELEASE
        if target.is_dir():
            if CURRENT_LINK.is_symlink() or CURRENT_LINK.exists():
                CURRENT_LINK.unlink(missing_ok=True)
            CURRENT_LINK.symlink_to(target.resolve())
    def test_bundle_creates_dual_release(self) -> None:
        release_id = "test_dual_bundle"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "bundle",
                "--release-id",
                release_id,
                "-n",
                "pytest dual",
                "--force",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, proc.returncode, proc.stderr + proc.stdout)
        release_dir = REPO_ROOT / "config" / "strategies" / "releases" / release_id
        self.assertTrue((release_dir / "fast_1m.yaml").is_file())
        self.assertTrue((release_dir / "us_fast_5m.yaml").is_file())
        manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest.get("bundle"))
        self.assertEqual(sorted(manifest.get("files") or []), ["fast_1m.yaml", "us_fast_5m.yaml"])

    def test_bundle_activate_updates_current(self) -> None:
        release_id = "test_dual_active"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "bundle",
                "--release-id",
                release_id,
                "--activate",
                "--force",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, proc.returncode, proc.stderr + proc.stdout)
        current = (REPO_ROOT / "config" / "strategies" / "current").resolve()
        self.assertEqual(current.name, release_id)
        self.assertTrue((current / "us_fast_5m.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
