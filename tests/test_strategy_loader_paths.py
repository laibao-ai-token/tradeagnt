"""Strategy path resolution for timestamp release folders."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradecat.core.signals.strategy import StrategyLoader


@pytest.fixture()
def strategies_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "config" / "strategies"
    release = root / "releases" / "20260101_120000"
    release.mkdir(parents=True)
    (release / "demo.yaml").write_text(
        "name: demo\nmarket: crypto\nsymbols: [BTC_USDT]\ntimeframe: 5m\nindicators: []\nrules: []\n",
        encoding="utf-8",
    )
    (root / "current").symlink_to(release, target_is_directory=True)
    monkeypatch.setattr(StrategyLoader, "_SEARCH_PATHS", [root])
    return root


def test_resolve_bare_filename_via_current(strategies_tree: Path) -> None:
    path = StrategyLoader.resolve_path("demo.yaml")
    assert path.name == "demo.yaml"
    assert "releases" in str(path)
    assert "20260101_120000" in str(path)


def test_resolve_explicit_release_path(strategies_tree: Path) -> None:
    path = StrategyLoader.resolve_path("releases/20260101_120000/demo.yaml")
    assert path.is_file()


def test_load_from_current_alias(strategies_tree: Path) -> None:
    cfg = StrategyLoader.load("current/demo.yaml")
    assert cfg.name == "demo"
