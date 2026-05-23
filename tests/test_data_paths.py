"""tradeagnt data/ vs legacy libs/ signal DB resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from tradecat.core.paper_trading import paths


def test_prefers_data_dir_when_both_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    (tmp_path / "src" / "tradecat").mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    legacy = tmp_path / paths._LEGACY_REL
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    (data_dir / "signal_history.db").write_bytes(b"data")

    monkeypatch.delenv("SIGNAL_DB_PATH", raising=False)
    resolved = paths.default_signal_db_path(tmp_path)
    assert resolved == data_dir / "signal_history.db"


def test_falls_back_to_legacy_when_data_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    (tmp_path / "src" / "tradecat").mkdir(parents=True)
    legacy = tmp_path / paths._LEGACY_REL
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")

    monkeypatch.delenv("SIGNAL_DB_PATH", raising=False)
    resolved = paths.default_signal_db_path(tmp_path)
    assert resolved == legacy


def test_signal_db_path_env_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom.db"
    custom.write_bytes(b"x")
    monkeypatch.setenv("SIGNAL_DB_PATH", str(custom))
    assert paths.default_signal_db_path(tmp_path) == custom.resolve()
